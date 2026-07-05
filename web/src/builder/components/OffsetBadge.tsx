/** Timing-lock indicator: verification state + xcorr quality from shape meta.
 * Display-only (Phase 5 dropped the manual offset slider). */
import type { AudioShapeMeta } from '../types';

export default function OffsetBadge({ meta }: { meta: AudioShapeMeta | null }) {
  if (!meta) return null;
  const v = meta.offset_verification ?? 'unverified';
  const off = Number(meta.timestamp_offset_ms ?? 0);
  const offStr = off !== 0 ? ` ${off >= 0 ? '+' : ''}${off}ms` : '';
  const q = Number(meta.offset_quality ?? 0);

  const [bg, fg, label] =
    v === 'user_verified' ? ['#2e7d32', '#fff', `User-verified${offStr}`]
    : v === 'auto_verified' ? ['#1565c0', '#fff', `Auto-calibrated${offStr}`]
    : ['#424242', '#aaa', 'Timing unverified'];

  const dot = q >= 0.7 ? '#1db954' : q >= 0.4 ? '#e6b122' : '#c62828';

  return (
    <span
      title={`Offset lock — ${label}${q > 0 ? ` · quality ${(q * 100).toFixed(0)}%` : ' · no quality score yet'}`}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '2px 8px',
               borderRadius: 10, fontSize: 11, background: bg, color: fg, whiteSpace: 'nowrap' }}
    >
      {label}
      {v !== 'unverified' && q > 0 && (
        <>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: dot, flex: 'none' }} />
          {(q * 100).toFixed(0)}%
        </>
      )}
    </span>
  );
}
