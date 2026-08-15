/** SPECTRA-native trigger authoring strip — click-to-place, drag-to-move,
 * click to edit, drag out of the band to delete. Same interaction shape as
 * TimelineBar's legacy markers (Phase 2 there), typed for SpectraTrigger and
 * color-coded by action kind instead of by legacy event. Phone-usable:
 * pointer events + touch-action: none, same as the rest of the timeline. */
import { useRef, useState } from 'react';
import type { SpectraTrigger, TriggerActionKind } from '../../types';
import type { Win } from '../canvas/frame';

const KIND_COLOR: Record<TriggerActionKind, string> = {
  fire_scene: '#a855f7',       // violet — matches the SPECTRA purple
  fire_response: '#f59e0b',    // amber
  select_color_set: '#14b8a6', // teal
  fire_scene_update: '#ef4444', // red — "major change", distinct from the flare amber
};

const KIND_LABEL: Record<TriggerActionKind, string> = {
  fire_scene: 'Fire scene',
  fire_response: 'Fire response',
  select_color_set: 'Select colour set',
  fire_scene_update: 'Fire update',
};

export function actionSummary(t: SpectraTrigger, sceneName: (id: string) => string): string {
  const a = t.action;
  if (a.kind === 'fire_scene') {
    const target = a.scene_id ? (sceneName(a.scene_id) || '—') : 'kernel picks';
    const prefix = t.source === 'generated' ? 'Seeded — ' : '';
    return `${prefix}${KIND_LABEL.fire_scene}: ${target} @ ⚡${a.intensity.toFixed(2)}`;
  }
  if (a.kind === 'fire_response') return `${KIND_LABEL.fire_response}: ${a.event_class} @ ⚡${a.intensity.toFixed(2)}`;
  if (a.kind === 'fire_scene_update') return `${KIND_LABEL.fire_scene_update} @ ⚡${a.intensity.toFixed(2)}`;
  return `${KIND_LABEL.select_color_set}: ${a.set_id || '—'}`;
}

export default function SpectraTriggerBar({
  durationMs,
  triggers,
  sceneName,
  getWin,
  getNowMs,
  onEdit,
  onMove,
  onDelete,
  onCreate,
}: {
  durationMs: number;
  triggers: SpectraTrigger[];
  sceneName: (id: string) => string;
  getWin: () => Win;
  getNowMs: () => number | null;
  onEdit: (triggerId: string) => void;
  onMove: (triggerId: string, ms: number) => void;
  onDelete: (triggerId: string) => void;
  onCreate: (ms: number) => void;
}) {
  const barRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ text: string; leftPct: string } | null>(null);

  const dur = Math.max(1, durationMs);
  const win = getWin();
  const now = getNowMs();
  const pct = (ms: number) => `${Math.max(0, Math.min(100, (ms / dur) * 100))}%`;
  const msAt = (clientX: number) => {
    const rect = barRef.current!.getBoundingClientRect();
    return Math.max(0, Math.min(dur, ((clientX - rect.left) / Math.max(1, rect.width)) * dur));
  };

  const dragMarker = (t: SpectraTrigger) => (ev: React.PointerEvent) => {
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
      style={{
        position: 'relative', height: 26, background: 'var(--surface2)',
        border: '1px solid var(--border)', borderRadius: 6,
        userSelect: 'none', touchAction: 'none',
      }}
      title="Double-click to place a trigger; drag to move; click to edit; drag out to delete"
    >
      {now !== null && (
        <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: pct(now),
                      background: 'rgba(168,85,247,0.18)', pointerEvents: 'none' }} />
      )}
      <div style={{ position: 'absolute', top: 0, bottom: 0, left: pct(win.startMs),
                    width: `${Math.max(0.5, ((win.endMs - win.startMs) / dur) * 100)}%`,
                    background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.2)',
                    pointerEvents: 'none' }} />
      {hover && (
        <div style={{
          position: 'absolute', bottom: '100%', left: hover.leftPct, transform: 'translate(-50%, -4px)',
          background: 'rgba(0,0,0,0.85)', color: '#fff', fontSize: 11, padding: '2px 8px',
          borderRadius: 4, whiteSpace: 'nowrap', pointerEvents: 'none', zIndex: 5,
        }}>
          {hover.text}
        </div>
      )}
      {triggers.map((t) => (
        <div
          key={t.id}
          onPointerDown={dragMarker(t)}
          onPointerEnter={() => setHover({ text: actionSummary(t, sceneName), leftPct: pct(t.timestamp_ms) })}
          onPointerLeave={() => setHover(null)}
          style={{
            position: 'absolute', top: 2, bottom: 2, left: pct(t.timestamp_ms), width: 5,
            marginLeft: -2, background: KIND_COLOR[t.action.kind],
            opacity: t.enabled ? 1 : 0.35, borderRadius: 1, cursor: 'grab',
            // Seeded (generated, untouched) triggers get a dashed outline —
            // still every gesture a hand-placed one has (move/edit/delete).
            border: t.source === 'generated' ? '1px dashed rgba(255,255,255,0.6)' : 'none',
          }}
        />
      ))}
    </div>
  );
}
