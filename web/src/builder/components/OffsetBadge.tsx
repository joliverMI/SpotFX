/** Timing-lock indicator: verification state + xcorr quality from shape meta.
 * ✎ opens a minimal manual write (PATCH /audio-shape/offset, user_verified);
 * ✕ clears back to 0 / unverified so auto-calibration can relearn. */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { AudioShapeMeta } from '../types';

export default function OffsetBadge({ meta, uri }: { meta: AudioShapeMeta | null; uri?: string | null }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draftMs, setDraftMs] = useState('');
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

  const write = async (ms: number, verification: string) => {
    if (!uri) return;
    try {
      await api('PATCH',
        `/audio-shape/offset?uri=${encodeURIComponent(uri)}&timestamp_offset_ms=${ms}` +
        `&offset_verification=${verification}`);
      void qc.invalidateQueries({ queryKey: ['shape-meta', uri] });
    } catch (e) {
      console.error('[OffsetBadge] offset write failed', e);
    }
    setEditing(false);
  };

  if (editing) {
    const commit = () => {
      const ms = Math.max(-3000, Math.min(3000, parseInt(draftMs) || 0));
      void write(ms, 'user_verified');
    };
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
        onClick={(e) => e.stopPropagation()}>
        <input type="number" step={10} value={draftMs} autoFocus style={{ width: 80, fontSize: 11 }}
          title="Manual shape offset (ms, −3000…3000)"
          onChange={(e) => setDraftMs(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEditing(false); }} />
        <button style={{ fontSize: 11, padding: '1px 6px' }} onClick={commit}>Save</button>
        <button style={{ fontSize: 11, padding: '1px 6px' }} onClick={() => setEditing(false)}>Cancel</button>
      </span>
    );
  }

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
      {uri && (
        <span style={{ cursor: 'pointer', opacity: 0.8 }} title="Set the shape offset manually (user-verified)"
          onClick={(e) => { e.stopPropagation(); setDraftMs(String(off)); setEditing(true); }}>✎</span>
      )}
      {uri && v !== 'unverified' && (
        <span style={{ cursor: 'pointer', opacity: 0.8 }} title="Clear the offset (back to unverified — auto-calibration relearns)"
          onClick={(e) => { e.stopPropagation(); void write(0, 'unverified'); }}>✕</span>
      )}
    </span>
  );
}
