/** Lock history — top panel of the Timing page. Shows the last 10 distinct
 * songs' lock outcomes (grade, time-to-lock, offset moved); typing in the
 * search box switches to a full-history search (every stored play matching
 * title/artist/uri/device). Clicking a row loads that song's timing dump. */
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiGet } from '../api/spotfx';
import HelpLink from '../help/HelpLink';

export interface LockEntry {
  at: string;
  uri: string;
  title?: string;
  artist?: string;
  device?: string;
  setlist_id?: string | null;
  play_type?: string;
  locked?: boolean;
  time_to_lock_ms?: number | null;
  offset_ms?: number;
  prev_offset_ms?: number | null;
  delta_ms?: number | null;
  quality?: number;
  n_windows?: number;
  grade?: string;
}

const GRADE_COLORS: Record<string, string> = {
  A: '#4caf50', B: '#8bc34a', C: '#ff9800', D: '#ff5722', F: '#f44336',
};

const fmtOffset = (v?: number | null): string =>
  v == null ? '—' : (v >= 0 ? '+' : '') + Math.round(v) + 'ms';

const fmtLockTime = (e: LockEntry): string => {
  if (e.time_to_lock_ms == null) return e.locked ? '?' : 'no lock';
  return (e.time_to_lock_ms / 1000).toFixed(1) + 's';
};

const fmtWhen = (iso: string): string => {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '—';
  const mins = Math.round((Date.now() - t) / 60000);
  if (mins < 1) return 'now';
  if (mins < 60) return `${mins}m ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)}h ago`;
  return new Date(t).toLocaleDateString();
};

function GradeChip({ grade, entry }: { grade?: string; entry: LockEntry }) {
  const g = grade || '—';
  const color = GRADE_COLORS[g] ?? 'var(--text-muted)';
  return (
    <span
      title={`Q=${(entry.quality ?? 0).toFixed(2)} · ${entry.locked ? 'hard lock' : 'no hard lock'} · ${entry.n_windows ?? 0} windows`}
      style={{
        display: 'inline-block', minWidth: 22, textAlign: 'center',
        padding: '1px 6px', borderRadius: 4, fontWeight: 700, fontSize: 12,
        color, border: `1px solid ${color}`, background: 'transparent',
      }}>
      {g}
    </span>
  );
}

export default function LockHistoryPanel({ activeUri, onPick }: {
  activeUri: string;
  onPick: (uri: string) => void;
}) {
  const [input, setInput] = useState('');
  const [q, setQ] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setQ(input.trim()), 250);
    return () => clearTimeout(t);
  }, [input]);

  const { data } = useQuery({
    queryKey: ['lock-history', q],
    queryFn: () => q
      ? apiGet<{ entries: LockEntry[] }>(`/lock-history/search?q=${encodeURIComponent(q)}&limit=100`)
      : apiGet<{ entries: LockEntry[] }>('/lock-history/recent?limit=10'),
    refetchInterval: 15000,
    retry: false,
  });

  const entries = data?.entries ?? [];
  const showDevice = entries.some((e) => (e.device ?? 'default') !== 'default');
  const th = (label: string, right = true): React.ReactNode => (
    <th key={label} style={{
      textAlign: right ? 'right' : 'left', padding: '3px 8px',
      borderBottom: '1px solid var(--border)', color: 'var(--text-muted)',
      fontSize: 10, textTransform: 'uppercase', fontWeight: 'normal',
    }}>{label}</th>
  );
  const td = (right = true): React.CSSProperties => ({
    textAlign: right ? 'right' : 'left', padding: '4px 8px',
    borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap',
  });

  return (
    <div className="card" style={{ padding: '12px 16px', marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
          Lock history {q ? '(search)' : '— last 10 songs'}
        </h3>
        <HelpLink topic="timing-lock-history" title="Lock history help" />
        <input
          type="search"
          placeholder="Search history: title, artist, uri, device…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          style={{ marginLeft: 'auto', fontSize: 12, minWidth: 220 }}
        />
      </div>
      {!entries.length ? (
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {q ? 'No history entries match this search.' : 'No locks recorded yet — history fills in as songs play.'}
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, fontFamily: 'monospace' }}>
            <thead>
              <tr>
                {th('grade', false)}
                {th('song', false)}
                {th('time to lock')}
                {th('offset')}
                {th('Δ needed')}
                {th('Q')}
                {showDevice && th('device', false)}
                {th('when')}
              </tr>
            </thead>
            <tbody>
              {entries.map((e, i) => (
                <tr
                  key={`${e.uri}-${e.at}-${i}`}
                  onClick={() => onPick(e.uri)}
                  title="Click to load this song's timing data below"
                  style={{
                    cursor: 'pointer',
                    background: e.uri === activeUri ? 'var(--surface2)' : undefined,
                  }}>
                  <td style={td(false)}><GradeChip grade={e.grade} entry={e} /></td>
                  <td style={{ ...td(false), fontFamily: 'inherit', maxWidth: 320, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    <span style={{ fontWeight: 600 }}>{e.title || e.uri}</span>
                    {e.artist ? <span style={{ color: 'var(--text-muted)' }}> — {e.artist}</span> : null}
                  </td>
                  <td style={{ ...td(), color: e.time_to_lock_ms == null && !e.locked ? '#ff9800' : undefined }}>
                    {fmtLockTime(e)}
                  </td>
                  <td style={td()}>{fmtOffset(e.offset_ms)}</td>
                  <td style={td()}>{fmtOffset(e.delta_ms)}</td>
                  <td style={td()}>{(e.quality ?? 0).toFixed(2)}</td>
                  {showDevice && <td style={td(false)}>{e.device || 'default'}</td>}
                  <td style={{ ...td(), color: 'var(--text-muted)' }}>{fmtWhen(e.at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
