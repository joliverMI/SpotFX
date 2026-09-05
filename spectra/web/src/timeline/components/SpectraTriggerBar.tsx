/** SPECTRA-native trigger authoring strip — click-to-place, drag-to-move,
 * click to edit, drag out of the band to delete. Same interaction shape as
 * TimelineBar's legacy markers (Phase 2 there), typed for SpectraTrigger and
 * color-coded by action kind instead of by legacy event. Phone-usable:
 * pointer events + touch-action: none, same as the rest of the timeline. */
import { useRef, useState } from 'react';
import type { ResponseClass, SpectraTrigger, TriggerActionKind } from '../../types';
import type { Win } from '../canvas/frame';
import { isPhaseStretchClass, phaseBlendSpan } from '../phaseBlend';
import type { PhaseBlendSpan } from '../phaseBlend';

const KIND_COLOR: Record<TriggerActionKind, string> = {
  fire_scene: '#a855f7',       // violet — matches the SPECTRA purple
  fire_response: '#f59e0b',    // amber — the "flare" default, i.e. a regular trigger
  select_color_set: '#14b8a6', // teal
  fire_scene_update: '#ef4444', // red — "major change", distinct from the flare amber
};

// Fire-response's own event_class further splits the amber "regular"
// colour above: charge/lull/drop are the phase-drive classes, each its own
// colour so they read apart from a plain flare (regular amber) and from
// each other at a glance while watching a sequence run.
export const RESPONSE_CLASS_COLOR: Record<ResponseClass, string> = {
  flare: KIND_COLOR.fire_response,
  charge: '#fbbf24', // amber-gold — building
  lull: '#38bdf8',   // sky blue — receding
  drop: '#ec4899',   // magenta — impact
};

/** The marker colour for a trigger: fire_response splits further by its
 * own event_class (charge/lull/drop vs. a plain flare); every other kind
 * uses its one KIND_COLOR. Shared with SpectraTriggerDialog's Class swatch
 * so the bar and the editor never disagree about what a colour means. */
export function triggerColor(t: SpectraTrigger): string {
  return t.action.kind === 'fire_response'
    ? RESPONSE_CLASS_COLOR[t.action.event_class]
    : KIND_COLOR[t.action.kind];
}

/** A charge/lull trigger's own blend, ready to draw: its ramp stretches to
 * the next trigger that will actually fire, then hangs at full for the last
 * ~10% of that gap. UNCONDITIONAL by class — see ../phaseBlend.ts for why
 * this is never keyed on a stored flag. "Next" mirrors
 * trigger_engine._next_trigger_gap_ms: the nearest later ENABLED trigger,
 * whatever kind it is; none means the flat class default, not the song end.
 *
 * A DISABLED charge/lull draws no blend at all — it never fires. */
export function phaseBlendSpans(triggers: SpectraTrigger[]): Array<PhaseBlendSpan & {
  triggerId: string; color: string;
}> {
  const enabled = triggers.filter((t) => t.enabled)
    .sort((a, b) => a.timestamp_ms - b.timestamp_ms);
  const out: Array<PhaseBlendSpan & { triggerId: string; color: string }> = [];
  for (const t of enabled) {
    if (t.action.kind !== 'fire_response' || !isPhaseStretchClass(t.action.event_class)) continue;
    const next = enabled.find((n) => n.timestamp_ms > t.timestamp_ms);
    out.push({
      ...phaseBlendSpan(t.action.event_class, t.timestamp_ms, next ? next.timestamp_ms : null),
      triggerId: t.id,
      color: triggerColor(t),
    });
  }
  return out;
}

const secs = (ms: number) => `${(ms / 1000).toFixed(1)}s`;

/** The hover suffix explaining a drawn blend, so the tint is never a shape
 * he has to guess at. Says outright when the length is the flat class
 * default rather than a real stretch. */
export function blendNote(b: PhaseBlendSpan | undefined): string {
  if (!b) return '';
  if (!b.stretched) return `  ⤳ blend ${secs(b.endMs - b.startMs)} (no next trigger — flat default)`;
  return `  ⤳ blend ${secs(b.endMs - b.startMs)} to the next trigger`
    + ` (ramp ${secs(b.rampEndMs - b.startMs)}, hang ${secs(b.endMs - b.rampEndMs)})`;
}

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
  const blends = phaseBlendSpans(triggers);
  const blendById = new Map(blends.map((b) => [b.triggerId, b]));
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
      {/* Charge/lull blend: the ramp to the next trigger, then the hang.
        * Drawn under the markers, tinted in the class's own colour — the
        * same read the legacy canvas gives an Override Blend trigger. */}
      {blends.map((b) => {
        const spanMs = Math.max(1, b.endMs - b.startMs);
        // Percentages of the SPAN, not of the song — the two children live
        // inside the span element, so its own length is their 100%.
        const rampPct = `${Math.max(0, Math.min(100, ((b.rampEndMs - b.startMs) / spanMs) * 100))}%`;
        const hangPct = `${Math.max(0, Math.min(100, ((b.endMs - b.rampEndMs) / spanMs) * 100))}%`;
        return (
          <div key={`blend-${b.triggerId}`} style={{
            position: 'absolute', top: 0, bottom: 0, left: pct(b.startMs),
            width: `${Math.max(0, ((b.endMs - b.startMs) / dur) * 100)}%`,
            pointerEvents: 'none', overflow: 'hidden',
          }}>
            <div style={{ position: 'absolute', top: 0, bottom: 0, left: 0, width: rampPct,
                          background: b.color, opacity: 0.22 }} />
            <div style={{ position: 'absolute', top: 0, bottom: 0, right: 0, width: hangPct,
                          background: b.color, opacity: 0.1 }} />
            <div style={{ position: 'absolute', bottom: 0, left: 0, width: rampPct, height: 2,
                          background: b.color, opacity: 0.55 }} />
            <div style={{ position: 'absolute', bottom: 0, right: 0, width: hangPct, height: 2,
                          background: b.color, opacity: 0.22 }} />
          </div>
        );
      })}
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
          onPointerEnter={() => setHover({
            text: actionSummary(t, sceneName) + blendNote(blendById.get(t.id)),
            leftPct: pct(t.timestamp_ms),
          })}
          onPointerLeave={() => setHover(null)}
          style={{
            position: 'absolute', top: 2, bottom: 2, left: pct(t.timestamp_ms), width: 5,
            marginLeft: -2, background: triggerColor(t),
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
