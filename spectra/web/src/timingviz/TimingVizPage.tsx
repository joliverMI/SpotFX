/** Timing Visualisation — read-only xcorr/anchor diagnostic dump
 * (port of frontend/timing-viz.html). ?uri= targets a song; defaults to the
 * currently-playing track server-side. */
import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { apiGet } from '../api/spotfx';
import { useToast } from '../components/Toast';
import LockHistoryPanel from './LockHistoryPanel';

interface Dump {
  uri?: string;
  live_timing?: Record<string, number | string>;
  spotify_track?: { interpolated_progress_ms?: number; polled_duration_ms?: number };
  audio_shape?: {
    title?: string; artist?: string;
    captured_duration_ms?: number;
    default_offset_ms?: number; default_quality?: number;
    offset_verification?: string;
    default_perception_trim_ms?: number;
    offset_history?: unknown[];
    anchor_candidates?: {
      timestamp_ms?: number; band?: string; rise_magnitude?: number;
      uniqueness?: number; template?: number[];
    }[];
  } | null;
  active_setlist?: {
    name?: string; xcorr_enabled?: boolean; xcorr_cut_buffer_ms?: number | null;
    recent_offset_deltas?: number[];
    slot?: {
      timestamp_offset_ms?: number; offset_quality?: number; perception_trim_ms?: number;
      anti_corr_count?: number; observed_cut_ms?: number;
      history?: { offset_ms: number; quality?: number; source?: string }[];
    };
  } | null;
  recent_sweeps?: {
    timestamp?: string; play_type?: string; n_windows?: number;
    prev_offset_ms?: number; final_offset_ms?: number; final_quality?: number;
    windows?: {
      start_ms?: number; difficulty?: number; winner?: string; offset_ms?: number;
      quality?: number; r_avg?: number; r_total?: number; r_low?: number; r_high?: number;
      old_r_avg?: number;
    }[];
  }[];
  xcorr_settings?: Record<string, number>;
  anchor_settings?: Record<string, number>;
}

const fmtMs = (v: unknown): string => {
  if (v == null || v === '') return '—';
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return (n >= 0 ? '+' : '') + Math.round(n) + 'ms';
};
const fmtNum = (v: unknown, digits = 2): string => {
  if (v == null || v === '') return '—';
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return n.toFixed(digits);
};

function KV({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', fontSize: 12 }}>
      <span style={{ color: 'var(--text-muted)' }}>{k}</span>
      <span style={{ fontFamily: 'monospace', textAlign: 'right' }}>{children}</span>
    </div>
  );
}

function PipeBox({ label, value, kind }: { label: string; value: string; kind?: 'input' | 'output' }) {
  return (
    <div style={{
      background: kind === 'output' ? 'rgba(255,152,0,0.08)' : 'var(--surface2)',
      border: `1px solid ${kind === 'input' ? '#4caf50' : kind === 'output' ? '#ff9800' : 'var(--border)'}`,
      borderRadius: 6, padding: '5px 9px', fontFamily: 'monospace', fontSize: 12, minWidth: 80, textAlign: 'center',
    }}>
      <span style={{ display: 'block', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.4px', marginBottom: 2 }}>
        {label}
      </span>
      {value}
    </div>
  );
}

const Op = ({ ch }: { ch: string }) => (
  <span style={{ color: '#ff9800', fontWeight: 'bold', fontSize: 14, padding: '0 4px' }}>{ch}</span>
);

function Pill({ warn, children }: { warn?: boolean; children: React.ReactNode }) {
  return (
    <span style={{
      display: 'inline-block', padding: '1px 6px', borderRadius: 10, fontSize: 11, marginRight: 6,
      background: warn ? 'rgba(255,152,0,0.08)' : 'rgba(76,175,80,0.08)',
      border: `1px solid ${warn ? '#ff9800' : '#4caf50'}`,
      color: warn ? '#ff9800' : '#4caf50',
    }}>
      {children}
    </span>
  );
}

export default function TimingVizPage() {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const uriParam = params.get('uri') ?? '';

  const { data: d, refetch, isLoading } = useQuery({
    queryKey: ['timing-viz', uriParam],
    queryFn: () => apiGet<Dump>(`/timing-viz/dump?uri=${encodeURIComponent(uriParam)}`),
    retry: false,
  });

  const uri = d?.uri || uriParam;
  const t = d?.live_timing ?? {};
  const s = d?.audio_shape;
  const sl = d?.active_setlist;
  const cut = useMemo(() => {
    if (!s) return 0;
    return Math.max(0, (s.captured_duration_ms ?? 0) - (d?.spotify_track?.polled_duration_ms ?? 0));
  }, [s, d]);

  const recapture = async () => {
    if (!uri) return;
    if (!confirm('Delete the stored audio shape, WAV, and librosa data for this song?\n\nIt will re-capture from the live device on the next play.')) return;
    try {
      const r = await fetch(`/api/audio-shape?uri=${encodeURIComponent(uri)}`, { method: 'DELETE' });
      if (!r.ok) throw new Error(await r.text());
      toast('Shape deleted — will re-capture on next play.', 'success');
      setTimeout(() => void refetch(), 500);
    } catch (e) {
      toast(`Delete failed: ${e instanceof Error ? e.message : e}`, 'error');
    }
  };

  const flags: React.ReactNode[] = [];
  if (s) {
    if (!(s.anchor_candidates ?? []).length) flags.push(<Pill warn key="na">no anchors</Pill>);
    if (cut > 6000) flags.push(<Pill warn key="lc">large cut {fmtMs(cut)}</Pill>);
  } else if (d) {
    flags.push(<Pill warn key="ns">no audio shape</Pill>);
  }
  if ((sl?.slot?.anti_corr_count ?? 0) >= 2) {
    flags.push(<Pill warn key="dr">drifting (anti-corr×{sl!.slot!.anti_corr_count})</Pill>);
  }

  const h3 = { margin: '0 0 8px 0', fontSize: 13, color: 'var(--text-muted)', textTransform: 'uppercase' as const, letterSpacing: '0.5px' };

  const historyPanel = (
    <LockHistoryPanel activeUri={uri} onPick={(u) => setParams({ uri: u })} />
  );

  if (!isLoading && d && !uri) {
    return (
      <>
        {historyPanel}
        <div className="card">
          <div style={{ fontWeight: 600, fontSize: 15 }}>No track playing.</div>
          <div style={{ color: 'var(--text-muted)', fontSize: 11, fontFamily: 'monospace' }}>
            Open this page while a song is playing, pick a song from the lock history above,
            or pass ?uri=spotify:track:... in the URL.
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      {historyPanel}
      <div className="card" style={{ padding: '12px 16px', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontWeight: 600, fontSize: 15 }}>
              {isLoading ? 'Loading…' : `${s?.artist || ''} — ${s?.title || uri}`}
            </div>
            <div style={{ color: 'var(--text-muted)', fontSize: 11, fontFamily: 'monospace' }}>{uri || '—'}</div>
          </div>
          <button style={{ marginLeft: 'auto', fontSize: 12 }} onClick={() => void refetch()}>Refresh</button>
          <button className="danger" style={{ fontSize: 12 }}
            title="Delete the stored audio shape so the song re-captures on next play."
            onClick={() => void recapture()}>
            Recapture shape
          </button>
        </div>
        <div style={{ marginTop: 8 }}>
          {flags.length ? flags : <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>no warnings</span>}
        </div>
      </div>

      {/* Pipeline */}
      <div className="card" style={{ padding: '14px 16px', marginBottom: 12 }}>
        <h3 style={{ ...h3, fontSize: 12 }}>Trigger fire-time pipeline</h3>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 14 }}>
          From Spotify-reported song time to the moment a trigger actually fires:
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
          <PipeBox label="song pos" value={fmtMs(d?.spotify_track?.interpolated_progress_ms)} kind="input" />
          <Op ch="+" />
          <PipeBox label="shape_offset" value={fmtMs(t.shape_offset_ms)} />
          <Op ch="+" />
          <PipeBox label="ledfx buf" value={fmtMs(t.ledfx_trigger_buffer_ms)} />
          <Op ch="+" />
          <PipeBox label="ledfx rtt" value={fmtMs(t.ledfx_rtt_ms)} />
          <span style={{ color: 'var(--text-muted)', fontSize: 14 }}>→</span>
          <PipeBox label="effective" value={fmtMs(t.effective_offset_ms)} kind="output" />
          <span style={{ margin: '0 12px', color: 'var(--text-muted)' }}>|</span>
          <PipeBox label="audio latency" value={`−${t.audio_latency_ms ?? 0}ms`} kind="input" />
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          Each box is a measured ms value at the time of dump. Any inaccuracy in the input boxes
          propagates straight to the output. The <strong>shape_offset_ms</strong> term is the only
          one xcorr controls — everything else is config or live RTT.
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div className="card" style={{ padding: '12px 16px' }}>
          <h3 style={h3}>Stored audio shape</h3>
          {!s ? (
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>No audio shape stored for this song.</div>
          ) : (
            <>
              <KV k="captured duration">{fmtMs(s.captured_duration_ms)}</KV>
              <KV k="polled duration">{fmtMs(d?.spotify_track?.polled_duration_ms ?? 0)}</KV>
              <KV k="cut (captured − polled)"><strong>{fmtMs(cut)}</strong></KV>
              <KV k="default offset">{fmtMs(s.default_offset_ms)} Q={fmtNum(s.default_quality)}</KV>
              <KV k="verification">{s.offset_verification ?? '—'}</KV>
              <KV k="default trim">{fmtMs(s.default_perception_trim_ms ?? 0)}</KV>
              <KV k="history entries">{String((s.offset_history ?? []).length)}</KV>
              <KV k="anchor candidates">{String((s.anchor_candidates ?? []).length)}</KV>
            </>
          )}
        </div>

        <div className="card" style={{ padding: '12px 16px' }}>
          <h3 style={h3}>Set List context</h3>
          {!sl ? (
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>No active Set List.</div>
          ) : (
            <>
              <KV k="name">{sl.name ?? '—'}</KV>
              <KV k="xcorr enabled">{sl.xcorr_enabled ? <Pill>yes</Pill> : <Pill warn>no</Pill>}</KV>
              <KV k="cut buffer override">{fmtMs(sl.xcorr_cut_buffer_ms)}</KV>
              <KV k="slot offset">{fmtMs(sl.slot?.timestamp_offset_ms)} Q={fmtNum(sl.slot?.offset_quality)}</KV>
              <KV k="perception trim">{fmtMs(sl.slot?.perception_trim_ms ?? 0)}</KV>
              <KV k="anti-corr count">{String(sl.slot?.anti_corr_count ?? 0)}</KV>
              <KV k="observed cut">{fmtMs(sl.slot?.observed_cut_ms)}</KV>
              <KV k="history (latest first)">
                {(sl.slot?.history ?? []).map((hh, i) => (
                  <span key={i}>{hh.offset_ms >= 0 ? '+' : ''}{hh.offset_ms}ms[Q{fmtNum(hh.quality)} {hh.source || 'sweep'}]<br /></span>
                ))}
                {!(sl.slot?.history ?? []).length && '—'}
              </KV>
              <KV k="recent deltas">
                {(sl.recent_offset_deltas ?? []).map((v) => fmtMs(v)).join(', ') || '—'}
              </KV>
            </>
          )}
        </div>

        <div className="card" style={{ padding: '12px 16px', gridColumn: '1/-1' }}>
          <h3 style={h3}>Early-feature anchor candidates</h3>
          {!(s?.anchor_candidates ?? []).length ? (
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              No anchor candidates stored. Re-capture to re-run anchor detection on the latest device.
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, fontFamily: 'monospace' }}>
                <thead>
                  <tr>
                    {['#', 'at', 'band', 'rise', 'uniqueness', 'template'].map((hh) => (
                      <th key={hh} style={{ textAlign: 'left', padding: '4px 8px', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase' }}>
                        {hh}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {s!.anchor_candidates!.map((a, i) => (
                    <tr key={i}>
                      <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)' }}>{i + 1}</td>
                      <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)' }}>{fmtMs(a.timestamp_ms)}</td>
                      <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)' }}>{a.band}</td>
                      <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)' }}>{fmtNum(a.rise_magnitude)}</td>
                      <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)' }}>{fmtNum(a.uniqueness)}</td>
                      <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)' }}>{(a.template ?? []).length} samples</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="card" style={{ padding: '12px 16px', gridColumn: '1/-1' }}>
          <h3 style={h3}>Recent xcorr sweeps</h3>
          {!(d?.recent_sweeps ?? []).length && (
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>No sweep history in the diagnostic CSV for this URI.</div>
          )}
          {(d?.recent_sweeps ?? []).map((sw, si) => (
            <div key={si} style={{ marginBottom: 12, padding: '10px 14px', background: 'var(--surface2)', borderRadius: 6 }}>
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: 12, marginBottom: 6, alignItems: 'baseline' }}>
                <span style={{ color: 'var(--text-muted)', fontFamily: 'monospace' }}>{sw.timestamp || '—'}</span>
                <span style={{ padding: '1px 6px', borderRadius: 3, fontSize: 10, background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                  {sw.play_type || '—'}
                </span>
                <span>n={sw.n_windows ?? 0}</span>
                <span>prev={fmtMs(sw.prev_offset_ms)}</span>
                <span style={{ color: 'var(--accent)', fontWeight: 600, fontFamily: 'monospace' }}>
                  final={fmtMs(sw.final_offset_ms)} Q={fmtNum(sw.final_quality)}
                </span>
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontFamily: 'monospace' }}>
                  <thead>
                    <tr>
                      {['start', 'diff', 'winner', 'offset', 'Q', 'r_avg', 'r_total', 'r_low', 'r_high', 'old_r'].map((hh) => (
                        <th key={hh} style={{ textAlign: 'right', padding: '2px 6px', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)', fontWeight: 'normal', textTransform: 'uppercase', fontSize: 10 }}>
                          {hh}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(sw.windows ?? []).map((w, wi) => (
                      <tr key={wi}>
                        <td style={td()}>{fmtMs(w.start_ms)}</td>
                        <td style={td()}>{fmtNum(w.difficulty)}</td>
                        <td style={td(w.winner === 'NEW' ? '#4caf50' : w.winner === 'OLD' ? '#888' : undefined)}>{w.winner || '—'}</td>
                        <td style={td()}>{fmtMs(w.offset_ms)}</td>
                        <td style={td()}>{fmtNum(w.quality)}</td>
                        <td style={td()}>{fmtNum(w.r_avg)}</td>
                        <td style={td()}>{fmtNum(w.r_total)}</td>
                        <td style={td()}>{fmtNum(w.r_low)}</td>
                        <td style={td()}>{fmtNum(w.r_high)}</td>
                        <td style={td()}>{fmtNum(w.old_r_avg)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>

        <div className="card" style={{ padding: '12px 16px', gridColumn: '1/-1' }}>
          <h3 style={h3}>Settings affecting this song</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>xcorr settings</div>
              <KV k="global threshold">{fmtNum(d?.xcorr_settings?.global_threshold)}</KV>
              <KV k="wide min r">{fmtNum(d?.xcorr_settings?.wide_min_r)}</KV>
              <KV k="wide top1 margin">{fmtNum(d?.xcorr_settings?.wide_top1_margin)}</KV>
              <KV k="high confidence r">{fmtNum(d?.xcorr_settings?.high_confidence_r)}</KV>
              <KV k="save min Q">{fmtNum(d?.xcorr_settings?.save_min_quality)}</KV>
              <KV k="save min confirm">{fmtNum(d?.xcorr_settings?.save_min_confirm)}</KV>
              <KV k="save confirm tol">{fmtMs(d?.xcorr_settings?.save_confirm_tol_ms)}</KV>
              <KV k="search base">{fmtMs(d?.xcorr_settings?.search_ms_base)}</KV>
              <KV k="cut buffer">{fmtMs(d?.xcorr_settings?.cut_buffer_ms)}</KV>
            </div>
            <div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>anchor settings</div>
              <KV k="scan window">{fmtMs(d?.anchor_settings?.scan_window_ms)}</KV>
              <KV k="template radius">{fmtMs(d?.anchor_settings?.template_radius_ms)}</KV>
              <KV k="min uniqueness">{fmtNum(d?.anchor_settings?.min_uniqueness)}</KV>
              <KV k="min rise ratio">{fmtNum(d?.anchor_settings?.min_rise_ratio)}</KV>
              <KV k="max candidates">{String(d?.anchor_settings?.max_candidates ?? '—')}</KV>
              <KV k="search radius">{fmtMs(d?.anchor_settings?.search_radius_ms)}</KV>
              <KV k="min match Q">{fmtNum(d?.anchor_settings?.min_match_q)}</KV>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

const td = (color?: string): React.CSSProperties => ({
  textAlign: 'right', padding: '2px 6px', borderBottom: '1px solid var(--border)',
  ...(color ? { color, fontWeight: color === '#4caf50' ? 600 : undefined } : {}),
});
