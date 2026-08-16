/** Sonic's token-usage strip — his own ask, on the review page: "how much
 * token usage Sonic has used for the last query, the last day, and the
 * last week." Every number here is REAL REPORTED USAGE captured off the
 * model runtime's own response for that call (spectra/services/
 * sonic_usage.py) — never estimated from character counts. `day`/`week`
 * are FIXED periods anchored Monday 22:00 America/New_York, not rolling —
 * his own ruling, because that boundary is almost certainly aligned to
 * his subscription's own quota reset, so "what THIS PERIOD has used" also
 * reads as "roughly how much he has left" — the number that matters after
 * a quota exhausted on him without warning. */
import HelpLink from '../../help/HelpLink';
import { useSonicUsage } from '../../queries';
import type { SonicUsagePeriod } from '../../types';

const fmtInt = (n: number) => n.toLocaleString();

const fmtWhen = (ms: number) =>
  new Date(ms).toLocaleString(undefined, {
    timeZone: 'America/New_York', weekday: 'short', month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit',
  });

const fmtAgo = (ms: number) => {
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
};

function PeriodTile({ label, period, sinceLabel }: {
  label: string; period: SonicUsagePeriod; sinceLabel: string;
}) {
  return (
    <div style={{ flex: '1 1 160px', minWidth: 0 }}>
      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
        {fmtInt(period.total_tokens)}
        <span style={{ fontSize: 12, fontWeight: 400, color: 'var(--text-muted)' }}> tokens</span>
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {period.query_count} quer{period.query_count === 1 ? 'y' : 'ies'} · {sinceLabel} {fmtWhen(period.period_start_ms)}
        {period.cost_usd != null && ` · $${period.cost_usd.toFixed(3)}`}
      </div>
    </div>
  );
}

export default function SonicUsageCard() {
  const { data } = useSonicUsage();

  return (
    <div className="card">
      <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        Sonic token usage <HelpLink topic="sonic-token-usage" />
      </div>

      {!data ? (
        <p className="empty-note">Loading…</p>
      ) : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 20 }}>
          <div style={{ flex: '1 1 200px', minWidth: 0 }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Last query</div>
            {data.last_query ? (
              <>
                <div style={{ fontSize: 24, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
                  {fmtInt(data.last_query.total_tokens)}
                  <span style={{ fontSize: 12, fontWeight: 400, color: 'var(--text-muted)' }}> tokens</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span className={`badge ${data.last_query.backend === 'cli' ? 'badge-blue' : 'badge-gray'}`}>
                    {data.last_query.backend === 'cli' ? 'subscription' : 'API credits'}
                  </span>
                  <span>{fmtAgo(data.last_query.wall_ms)}</span>
                  {data.last_query.cost_usd != null && <span>· ${data.last_query.cost_usd.toFixed(3)}</span>}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                  {fmtInt(data.last_query.input_tokens)} in · {fmtInt(data.last_query.output_tokens)} out
                  {(data.last_query.cache_read_input_tokens > 0 || data.last_query.cache_creation_input_tokens > 0) &&
                    ` · ${fmtInt(data.last_query.cache_read_input_tokens + data.last_query.cache_creation_input_tokens)} cache`}
                </div>
              </>
            ) : (
              <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>No Sonic calls recorded yet</div>
            )}
          </div>

          <PeriodTile label="This day" period={data.day} sinceLabel="since" />
          <PeriodTile label="This week" period={data.week} sinceLabel="since" />
        </div>
      )}
    </div>
  );
}
