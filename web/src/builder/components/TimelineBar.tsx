/** Thin full-song bar: progress fill, zoom-region handles, trigger markers.
 * Marker interactions (Phase 2): drag = move time (drag out of band = delete),
 * click = edit, dblclick empty = create, right-click = armed place/reassign. */
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
  onEdit,
  onMove,
  onDelete,
  onCreate,
  onArmedContext,
}: {
  durationMs: number;
  triggers: MusicTrigger[];
  events: EventOption[];
  getWin: () => Win;
  getNowMs: () => number | null;
  follow: boolean;
  onManualWin: (win: Win) => void;
  onAdjustFollow: (edge: 'start' | 'end' | 'center', deltaMs: number) => void;
  onEdit: (triggerId: string) => void;
  onMove: (triggerId: string, ms: number) => void;
  onDelete: (triggerId: string) => void;
  onCreate: (ms: number) => void;
  /** right-click: place/reassign the armed palette event (no-op when disarmed) */
  onArmedContext: (ms: number, triggerId: string | null) => void;
}) {
  const barRef = useRef<HTMLDivElement>(null);
  const [, force] = useState(0);
  const [hover, setHover] = useState<{ name: string; leftPct: string } | null>(null);

  useEffect(() => {
    const t = setInterval(() => force((n) => n + 1), 100);
    return () => clearInterval(t);
  }, []);

  const dur = Math.max(1, durationMs);
  const win = getWin();
  const now = getNowMs();
  const pct = (ms: number) => `${Math.max(0, Math.min(100, (ms / dur) * 100))}%`;
  const msAt = (clientX: number) => {
    const rect = barRef.current!.getBoundingClientRect();
    return Math.max(0, Math.min(dur, ((clientX - rect.left) / Math.max(1, rect.width)) * dur));
  };

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

  const dragMarker = (t: MusicTrigger) => (ev: React.PointerEvent) => {
    if (ev.button !== 0) return;
    ev.preventDefault();
    ev.stopPropagation();
    const bar = barRef.current;
    if (!bar) return;
    (ev.target as HTMLElement).setPointerCapture(ev.pointerId);
    let moved = false;
    let outOfBand = false;
    const move = (e: PointerEvent) => {
      const rect = bar.getBoundingClientRect();
      if (Math.abs(e.clientX - ev.clientX) > 3 || Math.abs(e.clientY - ev.clientY) > 3) moved = true;
      outOfBand = e.clientY < rect.top - 20 || e.clientY > rect.bottom + 20;
      if (moved) onMove(t.id, Math.round(msAt(e.clientX) / 20) * 20);
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      if (outOfBand) onDelete(t.id);
      else if (!moved) onEdit(t.id);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  return (
    <div
      ref={barRef}
      onDoubleClick={(e) => onCreate(Math.round(msAt(e.clientX) / 20) * 20)}
      onContextMenu={(e) => { e.preventDefault(); onArmedContext(msAt(e.clientX), null); }}
      style={{
        position: 'relative', height: 26, background: 'var(--surface2)',
        border: '1px solid var(--border)', borderRadius: 6,
        userSelect: 'none', touchAction: 'none',
      }}
    >
      {now !== null && (
        <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: pct(now),
                      background: 'rgba(29,185,84,0.18)', pointerEvents: 'none' }} />
      )}
      <div style={{ position: 'absolute', top: 0, bottom: 0, left: pct(win.startMs),
                    width: `${Math.max(0.5, ((win.endMs - win.startMs) / dur) * 100)}%`,
                    background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.25)',
                    cursor: 'grab', zIndex: 2 }}
           onPointerDown={dragEdge('center')}>
        <div onPointerDown={dragEdge('start')}
             style={{ position: 'absolute', left: -3, top: 0, bottom: 0, width: 7, cursor: 'ew-resize' }} />
        <div onPointerDown={dragEdge('end')}
             style={{ position: 'absolute', right: -3, top: 0, bottom: 0, width: 7, cursor: 'ew-resize' }} />
      </div>
      {hover && (
        <div style={{
          position: 'absolute', bottom: '100%', left: hover.leftPct, transform: 'translate(-50%, -4px)',
          background: 'rgba(0,0,0,0.85)', color: '#fff', fontSize: 11, padding: '2px 8px',
          borderRadius: 4, whiteSpace: 'nowrap', pointerEvents: 'none', zIndex: 5,
        }}>
          {hover.name}
        </div>
      )}
      {triggers.map((t) => {
        const ev = events.find((e) => e.id === t.event_id);
        return (
          <div
            key={t.id}
            onPointerDown={dragMarker(t)}
            onPointerEnter={() => setHover({ name: ev?.name ?? t.event_id, leftPct: pct(t.timestamp_ms) })}
            onPointerLeave={() => setHover(null)}
            onContextMenu={(e) => { e.preventDefault(); e.stopPropagation(); onArmedContext(t.timestamp_ms, t.id); }}
            style={{
              position: 'absolute', top: 2, bottom: 2, left: pct(t.timestamp_ms), width: 5,
              marginLeft: -2, background: ev?.color ?? '#888', borderRadius: 1, cursor: 'grab',
              zIndex: 1,
            }}
          />
        );
      })}
    </div>
  );
}
