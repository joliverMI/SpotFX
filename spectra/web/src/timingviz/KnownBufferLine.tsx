/** THE KNOWN AUDIO BUFFER — one line on the timing page saying how far
 * his sound is running behind, what SPECTRA is doing about it, and (while
 * the application gate is shut) why that is nothing.
 *
 * Reads GET /spectra/api/timing/effects-fire-later — the SAME state block
 * GET /api/engine/status carries as `known_buffer`, built by one function
 * server-side, so this line and the status surface cannot describe his
 * room differently.
 *
 * TWO THINGS THIS MUST NOT MISREPRESENT, both load-bearing:
 *  - STALE IS NOT A FAULT. River re-measures on its own 15 s period, so a
 *    reading is already up to a period old when it arrives and a healthy
 *    steady state oscillates fresh/stale. It is drawn as an ordinary
 *    HOLDING state with its age, never as a warning.
 *  - NOTHING IS APPLIED while `apply_gate` is set. The line says so in
 *    words rather than showing a compensation figure a reader would take
 *    for something his lights are doing. */
import { useQuery } from '@tanstack/react-query';
import { apiGet } from '../api/client';
import HelpLink from '../help/HelpLink';

interface KnownBuffer {
  effects_fire_later_by_ms: number;
  published_ms: number | null;
  at: number | null;
  age_s: number | null;
  state: 'unconfigured' | 'fresh' | 'stale' | 'missing';
  source: string;
  via: string;
  floor_ms: number;
  ceiling_ms: number;
  update_period_s: number;
  stale_periods: number;
  flags: string[];
  reference_ms: number | null;
  compensation_ms: number;
  apply_gate: string;
  applied: boolean;
  sentence: string;
  url: string;
  river: {
    source?: string; stale?: boolean | null; age_ms?: number | null;
    held_age_ms?: number | null; epoch?: number | null;
    floor_clamped?: boolean | null; governed?: boolean | null;
    parec_buffer_ms?: number | null; flowing?: boolean | null;
  } | null;
  readings_seen: number;
  sse_connected: boolean;
}

const STATE_LABEL: Record<string, string> = {
  unconfigured: 'not configured',
  fresh: 'fresh',
  stale: 'holding',   // never the word "stale" on its own — see the header
  missing: 'missing',
};

export default function KnownBufferLine() {
  const { data } = useQuery({
    queryKey: ['known-buffer'],
    queryFn: () => apiGet<KnownBuffer>('/timing/effects-fire-later'),
    refetchInterval: 5000,
    retry: false,
  });
  if (!data) return null;
  const warn = data.state === 'missing' || data.state === 'unconfigured';
  return (
    <div className="card" style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <span style={{
          fontSize: 13, color: 'var(--text-muted)',
          textTransform: 'uppercase', letterSpacing: '0.5px',
        }}>
          Sound running behind
        </span>
        <HelpLink topic="known-audio-buffer" />
        <span style={{ fontFamily: 'monospace', fontSize: 18, fontWeight: 600 }}>
          {data.effects_fire_later_by_ms} ms
        </span>
        <span style={{
          display: 'inline-block', padding: '1px 6px', borderRadius: 10, fontSize: 11,
          background: warn ? 'rgba(255,152,0,0.08)' : 'rgba(76,175,80,0.08)',
          border: `1px solid ${warn ? '#ff9800' : '#4caf50'}`,
          color: warn ? '#ff9800' : '#4caf50',
        }}>
          {STATE_LABEL[data.state] ?? data.state}
          {data.age_s != null && data.state !== 'unconfigured'
            ? ` · ${data.age_s.toFixed(0)}s old` : ''}
        </span>
        {data.flags.map((f) => (
          <span key={f} style={{
            fontSize: 11, fontFamily: 'monospace', color: 'var(--text-muted)',
            border: '1px solid var(--border)', borderRadius: 10, padding: '1px 6px',
          }}>{f}</span>
        ))}
      </div>
      <div style={{ fontSize: 12, marginTop: 6 }}>{data.sentence}</div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4, fontFamily: 'monospace' }}>
        {data.applied
          ? `compensation ${data.compensation_ms >= 0 ? '+' : ''}${data.compensation_ms} ms later`
          : 'compensation 0 ms — nothing reaches the show clock'}
        {' · '}floor {data.floor_ms} ms{' · '}ceiling {data.ceiling_ms} ms (not a clamp)
        {data.reference_ms != null ? ` · reference ${data.reference_ms} ms` : ''}
        {' · '}River {data.river?.source || '—'}
        {data.river?.floor_clamped ? ' (floor_clamped)' : ''}
        {' · '}{data.sse_connected ? 'events connected' : 'events reconnecting'}
      </div>
      {!data.applied && data.apply_gate ? (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
          Why nothing is applied: with River's bounding half off it can only see the
          parec buffer, so this number is the contractual floor rather than a measured
          delay — applying it would push the lights 300–500&nbsp;ms behind the sound.
          Your A/V lead is untouched.
        </div>
      ) : null}
    </div>
  );
}
