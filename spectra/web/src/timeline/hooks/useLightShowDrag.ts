/** Dragging a Light Show High/Low Trigger flag directly on the audio-shape
 * canvas (the Admiral, 2026-10-08: "i can't seem to move the marker on the
 * audio shape") — see ../canvas/lightShowLayer.ts's own docstring for why
 * this never steals a hit from a SPECTRA trigger underneath.
 *
 * Same "no jump" + beat-snap precision as the full-song bar
 * (ShowCueBar.tsx, ../../lightshow/cueFlags.ts): the grab offset between
 * where the finger landed and the flag's own ms is captured once, at
 * pointerdown, and kept for the whole drag. */
import { useRef, useState } from 'react';
import { apiPut } from '../../api/client';
import { snapCueMs } from '../../lightshow/cueFlags';
import type { FrameGeom } from '../canvas/TimelineCanvas';
import type { Hit } from '../canvas/frame';

interface Drag {
  level: 'high' | 'low';
  /** flag's own ms at grab time, minus the pointer's own ms at grab time —
   *  added back on every move so the flag tracks the finger, never jumps
   *  to its raw position. */
  grabMs: number;
}

/** A boolean-returning subset of PointerHandlers (unlike that interface's
 *  own void-returning onHit/onDragMove/onDragEnd) — BuilderPage.tsx chains
 *  these the same way it already chains useDropSeqInteractions', stopping
 *  at the first handler that reports it consumed the gesture. */
interface LightShowPointer {
  onHit(hit: Hit, ev: PointerEvent, g: FrameGeom): boolean;
  onDragMove(ev: PointerEvent, g: FrameGeom): boolean;
  onDragEnd(ev: PointerEvent, g: FrameGeom): boolean;
}

export function useLightShowDrag(opts: {
  uri: string | null;
  durationMs: number;
  getBeats: () => { ms: number }[] | null;
  onChanged: () => void;
}) {
  const drag = useRef<Drag | null>(null);
  const lastMs = useRef<number | null>(null);
  const [liveMs, setLiveMs] = useState<{ level: 'high' | 'low'; ms: number } | null>(null);

  const rel = (ev: PointerEvent) => {
    const r = (ev.target as HTMLElement).getBoundingClientRect();
    return { x: ev.clientX - r.left };
  };

  const save = async (level: 'high' | 'low', ms: number) => {
    if (!opts.uri) return;
    await apiPut('/light-show/cues', { uri: opts.uri, level, timestamp_ms: ms }).catch(() => undefined);
    opts.onChanged();
  };

  const pointer: LightShowPointer = {
    onHit: (hit, ev, g) => {
      if (hit?.kind !== 'light-show-flag') return false;
      const { x } = rel(ev);
      drag.current = { level: hit.level, grabMs: hit.ms - g.xToTime(x) };
      lastMs.current = hit.ms;
      setLiveMs({ level: hit.level, ms: hit.ms });
      return true;
    },
    onDragMove: (ev, g) => {
      const d = drag.current;
      if (!d) return false;
      const { x } = rel(ev);
      const raw = g.xToTime(x) + d.grabMs;
      const ms = snapCueMs(raw, opts.durationMs, g.w, opts.getBeats());
      lastMs.current = ms;
      setLiveMs({ level: d.level, ms });
      return true;
    },
    onDragEnd: () => {
      const d = drag.current;
      if (!d) return false;
      drag.current = null;
      const ms = lastMs.current;
      lastMs.current = null;
      setLiveMs(null);
      if (ms !== null) void save(d.level, ms);
      return true;
    },
  };

  return { pointer, liveMs };
}
