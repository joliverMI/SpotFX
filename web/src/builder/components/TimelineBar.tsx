/** Thin full-song bar: progress fill, zoom-region handles, trigger markers.
 * Read-only in Phase 1 (marker editing lands in Phase 2). */
import { useEffect, useRef, useState } from 'react';
import type { MusicTrigger, EventOption } from '../types';
import type { Win } from '../canvas/frame';

export default function TimelineBar({
  durationMs,
  triggers,
  events,
  getWin,
  getNowMs,
  follow,
  onManualWin,
  onAdjustFollow,
  onMarkerClick,
}: {
  durationMs: number;
  triggers: MusicTrigger[];
  events: EventOption[];
  getWin: () => Win;
  getNowMs: () => number | null;
  follow: boolean;
  /** manual mode: absolute new bounds */
  onManualWin: (win: Win) => void;
  /** follow mode: handle drags adjust window/future seconds */
  onAdjustFollow: (edge: 'start' | 'end' | 'center', deltaMs: number) => void;
  onMarkerClick?: (triggerId: string) => void;
}) {
  const barRef = useRef<HTMLDivElement>(null);
  const [, force] = useState(0);

  // The zoom region + progress move continuously — cheap 10Hz refresh.
  useEffect(() => {
    const t = setInterval(() => force((n) => n + 1), 100);
    return () => clearInterval(t);
  }, []);

  const dur = Math.max(1, durationMs);
  const win = getWin();
  const now = getNowMs();
  const pct = (ms: number) => `${Math.max(0, Math.min(100, (ms / dur) * 100))}%`;

  const dragEdge = (edge: 'start' | 'end' | 'center') => (ev: React.PointerEvent) => {
    ev.preventDefault();
    ev.stopPropagation();
    const bar = barRef.current;
    if (!bar) return;
    (ev.target as HTMLElement).setPointerCapture(ev.pointerId);
    let lastX = ev.clientX;
    const move = (e: PointerEvent) => {
      const rect = bar.getBoundingClientRect();
      const deltaMs = ((e.clientX - lastX) / Math.max(1, rect.width)) * dur;
      lastX = e.clientX;
      if (follow) {
        onAdjustFollow(edge, deltaMs);
      } else {
        const w = getWin();
        if (edge === 'center') onManualWin({ startMs: w.startMs + deltaMs, endMs: w.endMs + deltaMs });
        else if (edge === 'start') onManualWin({ startMs: Math.min(w.startMs + deltaMs, w.endMs - 1000), endMs: w.endMs });
        else onManualWin({ startMs: w.startMs, endMs: Math.max(w.endMs + deltaMs, w.startMs + 1000) });
      }
    };
    const up = (e: PointerEvent) => {
      (ev.target as HTMLElement).releasePointerCapture(e.pointerId);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  return (
    <div
      ref={barRef}
      style={{
        position: 'relative', height: 26, background: 'var(--surface2)',
        border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden',
        userSelect: 'none', touchAction: 'none',
      }}
    >
      {now !== null && (
        <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: pct(now),
                      background: 'rgba(29,185,84,0.18)' }} />
      )}
      {/* zoom region */}
      <div style={{ position: 'absolute', top: 0, bottom: 0, left: pct(win.startMs),
                    width: `${Math.max(0.5, ((win.endMs - win.startMs) / dur) * 100)}%`,
                    background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.25)',
                    cursor: 'grab' }}
           onPointerDown={dragEdge('center')}>
        <div onPointerDown={dragEdge('start')}
             style={{ position: 'absolute', left: -3, top: 0, bottom: 0, width: 7, cursor: 'ew-resize' }} />
        <div onPointerDown={dragEdge('end')}
             style={{ position: 'absolute', right: -3, top: 0, bottom: 0, width: 7, cursor: 'ew-resize' }} />
      </div>
      {/* trigger markers */}
      {triggers.map((t) => {
        const ev = events.find((e) => e.id === t.event_id);
        return (
          <div
            key={t.id}
            title={ev?.name ?? t.event_id}
            onClick={() => onMarkerClick?.(t.id)}
            style={{
              position: 'absolute', top: 2, bottom: 2, left: pct(t.timestamp_ms), width: 3,
              background: ev?.color ?? '#888', borderRadius: 1, cursor: 'pointer',
            }}
          />
        );
      })}
    </div>
  );
}
