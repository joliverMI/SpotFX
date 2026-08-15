/** Prominent lock-confidence indicator: the monitor's rolling Pearson r over
 * the trailing span (the same signal the diff graph visualizes) plus the
 * monitor state machine (ok / suspect / recovering). */
import { useEffect, useState } from 'react';
import { rColor, MONITOR_MIN_R } from './layers';
import type { MonitorStatus } from './useDebugFeeds';

const STALE_MS = 12_000;

const STATE_LABEL: Record<string, string> = {
  ok: 'LOCKED',
  suspect: 'SUSPECT',
  recovering: 'RECOVERING',
};
const STATE_COLOR: Record<string, string> = {
  ok: '#00ff88',
  suspect: '#ffb300',
  recovering: '#ff5252',
};

export default function LockBadge({
  monitor,
  offsetMs,
  quality,
}: {
  monitor: MonitorStatus | null;
  offsetMs: number | null;
  quality: number | null;
}) {
  // Re-render every second so staleness flips without new messages.
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);

  const fresh = monitor && Date.now() - monitor.atWallMs < STALE_MS;
  const label = fresh ? STATE_LABEL[monitor.state] ?? monitor.state.toUpperCase()
    : offsetMs != null ? 'LOCK IDLE' : 'NO LOCK';
  const color = fresh ? STATE_COLOR[monitor.state] ?? '#888' : '#888';
  const r = fresh ? monitor.rollingR : null;

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap',
      padding: '8px 14px', borderRadius: 8,
      border: `1px solid ${color}55`, background: `${color}12`,
    }}>
      <span style={{
        fontSize: 13, fontWeight: 700, letterSpacing: '0.08em', color,
      }}>
        ● {label}
      </span>
      <span style={{ fontSize: 12, fontFamily: 'monospace', color: r !== null ? rColor(r) : 'var(--text-muted)' }}
        title={`Rolling Pearson r over the trailing monitor span — the matcher's live confidence in the current lock. Below ${MONITOR_MIN_R.toFixed(2)} counts as mismatch evidence; null (—) means the span was too flat/quiet to testify.`}>
        rolling r = {r !== null ? r.toFixed(2) : '—'}
      </span>
      <span style={{ fontSize: 12, fontFamily: 'monospace', color: 'var(--text-muted)' }}>
        offset {offsetMs != null ? `${offsetMs >= 0 ? '+' : ''}${offsetMs}ms` : '—'}
        {quality != null && quality > 0 ? `  Q=${quality.toFixed(2)}` : ''}
      </span>
      {fresh && monitor.recoveries > 0 && (
        <span style={{ fontSize: 11, color: '#ff5252' }}>
          {monitor.recoveries} recover{monitor.recoveries === 1 ? 'y' : 'ies'} this play
        </span>
      )}
      {!fresh && (
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {offsetMs != null ? 'xcorr idle — offset locked, monitor quiet' : 'no live match data'}
        </span>
      )}
    </div>
  );
}
