/** Scrolling trigger list with follow mode: past triggers fade, the
 * last-fired row is highlighted, the upcoming one gets the yellow edge. */
import { useEffect, useRef } from 'react';
import { fmtMs } from '../lib/time';
import type { DisplayTrigger } from './useNowProfile';

export default function TriggerListCard({
  triggers,
  lastFiredIdx,
  nextTriggerId,
  resolvedActions,
  follow,
  setFollow,
  flashId,
}: {
  triggers: DisplayTrigger[];
  lastFiredIdx: number;
  nextTriggerId: string | null;
  resolvedActions: Record<string, string>;
  follow: boolean;
  setFollow: (v: boolean) => void;
  flashId: string | null;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const autoScrolling = useRef(false);

  // Follow: scroll so ~3 past triggers stay visible above the current one.
  useEffect(() => {
    if (!follow || lastFiredIdx < 0) return;
    const t = setTimeout(() => {
      const wrap = wrapRef.current;
      const anchor = wrap?.querySelector<HTMLElement>(`[data-gidx="${lastFiredIdx}"]`);
      if (!wrap || !anchor) return;
      autoScrolling.current = true;
      const relTop = anchor.getBoundingClientRect().top - wrap.getBoundingClientRect().top + wrap.scrollTop;
      wrap.scrollTop = Math.max(0, relTop - (anchor.offsetHeight || 36) * 3);
      requestAnimationFrame(() => { autoScrolling.current = false; });
    }, 1000);
    return () => clearTimeout(t);
  }, [follow, lastFiredIdx]);

  return (
    <div className="card">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <div className="card-title" style={{ margin: 0 }}>Triggers</div>
        <button
          className={follow ? 'primary' : ''}
          style={{ fontSize: 11, padding: '2px 10px' }}
          onClick={() => setFollow(true)}
        >
          Follow
        </button>
      </div>
      <div
        ref={wrapRef}
        style={{ maxHeight: 280, overflowY: 'auto' }}
        onScroll={() => { if (!autoScrolling.current) setFollow(false); }}
      >
        {!triggers.length && (
          <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>No triggers in this profile.</div>
        )}
        {triggers.map((t, idx) => {
          const cls =
            lastFiredIdx >= 0 && idx < lastFiredIdx ? ' trigger-past'
            : lastFiredIdx >= 0 && idx === lastFiredIdx ? ' trigger-current'
            : '';
          const next = t.id === nextTriggerId ? ' next' : '';
          return (
            <div
              key={t.id}
              data-gidx={idx}
              className={`trigger-row${cls}${next}`}
              style={flashId === t.id ? { background: 'rgba(255,215,0,0.15)' } : undefined}
            >
              <div className="trigger-color-dot" style={{ background: t.color }} />
              <span className="trigger-ts">{fmtMs(t.timestamp_ms)}</span>
              <span className="trigger-name">{t.name}</span>
              <span className="trigger-action">{resolvedActions[t.id] ?? ''}</span>
              <span className="trigger-labels">{t.labels.join(', ')}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
