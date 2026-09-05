/** Lock history — top panel of the Timing page. Shows the last 10 distinct
 * songs' lock outcomes (grade, time-to-lock, offset moved); typing in the
 * search box switches to a full-history search (every stored play matching
 * title/artist/uri/device). Clicking a row loads that song's timing dump.
 *
 * Also carries the PIPELINE DRIFT line (GET /lock-history/drift): the common
 * offset movement across a whole listening session — the signature of an
 * audio-chain latency change, which per-song saves otherwise absorb quietly —
 * with an alarm before the ~3s point where locks start failing. First plays
 * are split from repeat plays (summary + "1st" chip) so an album of new
 * songs can't read as a room failure. */
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

interface DriftSession {
  start_at: string;
  end_at: string;
  plays: number;
  baselined: number;
  median_residual_ms: number | null;
}

interface DriftStatus {
  sessions: DriftSession[];
  current: DriftSession | null;
  alarm: boolean;
  alarm_threshold_ms: number;
  min_baselined: number;
}

const fmtDriftS = (ms: number): string =>
  `${ms >= 0 ? '+' : '-'}${(Math.abs(ms) / 1000).toFixed(1)}s`;

/** The pipeline-drift line: each play's winning offset vs that song's own
 * older baseline, median'd per listening session. Per-song quirks cancel;
 * what survives is the common component only an audio-chain latency change
 * produces. Alarms past the threshold — before the ~3s stale-offset error
 * where the lock search starts failing outright. */
function DriftStrip() {
  const { data } = useQuery({
    queryKey: ['lock-history-drift'],
    queryFn: () => apiGet<DriftStatus>('/lock-history/drift'),
    refetchInterval: 30000,
    retry: false,
  });
  if (!data) return null;
  const cur = data.current;
  const alarm = data.alarm;
  const color = alarm ? '#f44336' : cur ? '#4caf50' : 'var(--text-muted)';
  const trend = [...data.sessions].reverse()
    .filter((s) => s.median_residual_ms != null && s.baselined >= data.min_baselined)
    .map((s) => fmtDriftS(s.median_residual_ms as number));
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
      padding: '6px 10px', marginBottom: 8, borderRadius: 6,
      border: `1px solid ${color}55`, background: alarm ? `${color}18` : `${color}0d`,
    }}>
      <span style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--text-muted)' }}>
        Pipeline drift <HelpLink topic="timing-pipeline-drift" title="What the drift line measures" />
      </span>
      {cur ? (
        <>
          <span
            style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: 13, color }}
            title={`Median of ${cur.baselined} repeat plays' winning offsets vs their own older baselines, over the session that started ${new Date(cur.start_at).toLocaleString()}. Alarms at ±${(data.alarm_threshold_ms / 1000).toFixed(1)}s.`}>
            {fmtDriftS(cur.median_residual_ms as number)}
          </span>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {cur.baselined} repeat plays · session {fmtWhen(cur.start_at)}
          </span>
          {alarm && (
            <span style={{ fontSize: 11, fontWeight: 700, color }}>
              ⚠ the whole room's audio timing has moved — locks start failing near ±3s; check the audio chain
            </span>
          )}
          {trend.length >= 2 && (
            <span
              style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--text-muted)', marginLeft: 'auto' }}
              title="Session medians, oldest → newest">
              {trend.join(' → ')}
            </span>
          )}
        </>
      ) : (
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          not enough repeat plays to measure yet
        </span>
      )}
    </div>
  );
}

const GRADE_ORDER = ['A', 'B', 'C', 'D', 'F'];

const gradeCounts = (list: LockEntry[]): string =>
  GRADE_ORDER
    .map((g) => [g, list.filter((e) => (e.grade || '') === g).length] as const)
    .filter(([, n]) => n > 0)
    .map(([g, n]) => `${g}×${n}`)
    .join(' ');

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
  // A first-ever recorded play has no previous offset on record: it starts
  // from a cold baseline and its grade says nothing about the room.
  const firsts = entries.filter((e) => e.prev_offset_ms == null);
  const repeats = entries.filter((e) => e.prev_offset_ms != null);
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
      <DriftStrip />
      {firsts.length > 0 && entries.length > 0 && (
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: 11, marginBottom: 6, color: 'var(--text-muted)' }}>
          <span>
            Repeats ({repeats.length}):{' '}
            <span style={{ fontFamily: 'monospace' }}>{gradeCounts(repeats) || '—'}</span>
          </span>
          <span>
            First plays ({firsts.length}):{' '}
            <span style={{ fontFamily: 'monospace' }}>{gradeCounts(firsts) || '—'}</span>
            {' '}— graded separately: a first play starts cold, with no offset history
          </span>
        </div>
      )}
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
                  <td style={td(false)}>
                    <GradeChip grade={e.grade} entry={e} />
                    {e.prev_offset_ms == null && (
                      <span
                        title="First recorded play — no offset history; graded from a cold start"
                        style={{ marginLeft: 4, fontSize: 9, color: 'var(--text-muted)', border: '1px solid var(--border)', borderRadius: 3, padding: '0px 3px', verticalAlign: 'middle' }}>
                        1st
                      </span>
                    )}
                  </td>
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
