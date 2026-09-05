/** All-triggers list: fired current/past highlighting (WS trigger_fired),
 * sticky auto-scroll follow, click-to-edit, Delete All. */
import { useEffect, useRef, useState } from 'react';
import { onMessage } from '../../api/ws';
import { fmtMsTenths } from '../../lib/time';
import { useSticky } from '../../lib/useSticky';
import { isPhaseStretchClass } from '../phaseBlend';
import { useBuilderStore } from '../store';
import type { EventOption, MusicTrigger } from '../types';

export default function TriggerList({
  triggers,
  events,
  onImport,
}: {
  triggers: MusicTrigger[];
  events: EventOption[];
  onImport: () => void;
}) {
  const setEditing = useBuilderStore((s) => s.setEditingTrigger);
  const mutateWorking = useBuilderStore((s) => s.mutateWorking);
  const [listFollow, setListFollow] = useSticky('listFollow', true);
  const [firedId, setFiredId] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => onMessage('trigger_fired', (msg) => {
    const id = String(msg.trigger_id ?? '');
    if (id) setFiredId(id);
  }), []);

  // Auto-scroll the fired row into view — scrolling ONLY the list container
  // (scrollIntoView would scroll the page too, yanking the viewport around
  // during live playback).
  useEffect(() => {
    if (!listFollow || !firedId) return;
    const wrap = wrapRef.current;
    const row = wrap?.querySelector<HTMLElement>(`[data-tid="${firedId}"]`);
    if (!wrap || !row) return;
    wrap.scrollTo({
      top: row.offsetTop - wrap.clientHeight / 2 + row.clientHeight / 2,
      behavior: 'smooth',
    });
  }, [firedId, listFollow]);

  const sorted = [...triggers].sort((a, b) => a.timestamp_ms - b.timestamp_ms);
  const firedIdx = sorted.findIndex((t) => t.id === firedId);

  return (
    <>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{sorted.length} triggers</span>
        <span style={{ flex: 1 }} />
        <button style={{ fontSize: 11, padding: '3px 8px' }} onClick={onImport}
          title="Pull triggers from AI analysis or copy from another slot">
          Import…
        </button>
        <button className={listFollow ? 'primary' : ''} style={{ fontSize: 11, padding: '3px 8px' }}
          onClick={() => setListFollow((v) => !v)} title="Auto-scroll to the last fired trigger">
          Follow
        </button>
        <button className="danger" style={{ fontSize: 11, padding: '3px 8px' }}
          onClick={() => {
            if (confirm(`Delete all ${sorted.length} triggers?`)) {
              mutateWorking((t) => { t.splice(0, t.length); });
            }
          }}>
          Delete All
        </button>
      </div>
      <div ref={wrapRef} style={{ maxHeight: 300, overflowY: 'auto' }}>
        {sorted.map((t, i) => {
          const ev = events.find((e) => e.id === t.event_id);
          const state = firedIdx < 0 ? '' : i === firedIdx ? 'current' : i < firedIdx ? 'past' : '';
          return (
            <div
              key={t.id}
              data-tid={t.id}
              onClick={() => setEditing(t.id)}
              style={{
                display: 'flex', alignItems: 'center', gap: 8, padding: '4px 8px',
                borderRadius: 6, cursor: 'pointer', fontSize: 13,
                background: state === 'current' ? 'rgba(168,85,247,0.18)' : undefined,
                opacity: state === 'past' ? 0.55 : 1,
              }}
            >
              <span className="color-dot" style={{ background: ev?.color ?? '#888' }} />
              <span style={{ fontFamily: 'monospace', color: 'var(--text-muted)', width: 62 }}>
                {fmtMsTenths(t.timestamp_ms)}
              </span>
              <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {ev?.name ?? t.event_id}
              </span>
              {/* Charge/lull always blend (no flag to read — phaseBlend.ts),
                * so the badge is class-driven for them and flag-driven for
                * everything else. */}
              {(isPhaseStretchClass(ev?.event_type) || t.override_blend) && (
                <span title={isPhaseStretchClass(ev?.event_type)
                  ? 'Charge/lull always ramps until the next trigger — no setting to turn it off'
                  : 'Override Blend — ramps until the next trigger'}
                  style={{ color: 'var(--accent)', flex: 'none' }}>⤳</span>
              )}
              {t.labels.map((l) => <span key={l} className="chip">{l}</span>)}
              <span
                title={`Intensity ${(t.intensity ?? 0.5).toFixed(2)}`}
                style={{ width: 40, height: 5, background: 'var(--surface2)', borderRadius: 3, overflow: 'hidden', flex: 'none' }}
              >
                <span style={{ display: 'block', height: '100%', borderRadius: 3,
                               width: `${(t.intensity ?? 0.5) * 100}%`,
                               background: (t.intensity ?? 0.5) === 0.5 ? 'var(--text-muted)' : 'var(--accent)' }} />
              </span>
            </div>
          );
        })}
        {!sorted.length && <p className="empty-note">No triggers — double-click the canvas to add one.</p>}
      </div>
    </>
  );
}
