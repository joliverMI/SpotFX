/** Debug — sync/xcorr diagnostics (port of frontend/debug.html) built on the
 * builder's TimelineCanvas. The lock badge + rolling-R trace make lock state
 * and confidence explicit; mismatch spikes are highlighted in magenta. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost, api } from '../api/client';
import { onMessage } from '../api/ws';
import { useSettings } from '../api/queries';
import { useAudioShapeData, useAudioShapeMeta } from '../builder/queries';
import TimelineCanvas from '../builder/canvas/TimelineCanvas';
import TimelineBar from '../builder/components/TimelineBar';
import { diamonds, playhead } from '../builder/canvas/layers';
import type { LayerDataBag, ViewState } from '../builder/canvas/frame';
import { useFollowWindow } from '../builder/hooks/useFollowWindow';
import CollapsibleCard from '../components/CollapsibleCard';
import HelpLink from '../help/HelpLink';
import { useToast } from '../components/Toast';
import { ensureLiveState, getLiveProgressMs, useLiveStore } from '../live/liveStore';
import { DIFF_MIN_SPAN_MS } from './diff';
import { diffBands, rollingR, savedVsLive, spikes as spikesLayer, xcorrWins } from './layers';
import LockBadge from './LockBadge';
import { useDebugFeeds } from './useDebugFeeds';

const ALL_MARKS = {
  bass_drop: true, bass_start: true, bass_end: true, power_up: true,
  power_down: true, quiet: true, charging: true, tempo_change: true,
};
const NO_LIBROSA = {
  sections: false, beats: false, onsets: false, harmonic: false,
  bass: false, snare: false, mfcc: false,
};

const SHAPE_LAYERS = [savedVsLive, diamonds, xcorrWins, spikesLayer, playhead];
const DIFF_LAYERS = [diffBands, rollingR, spikesLayer, playhead];

const LIVE_EDGE_STALE_MS = 5000;

const LEDFX_EVENT_STYLE: Record<string, { label: string; color: string }> = {
  held: { label: 'HELD', color: '#ffb300' },
  shed: { label: 'SHED', color: '#ff5252' },
  breaker_open: { label: 'BREAKER', color: '#ff5252' },
  recycled: { label: 'RECYCLED', color: '#40c4ff' },
  recovered: { label: 'RECOVERED', color: '#00ff88' },
};

function agoStr(deltaSec: number): string {
  const d = Math.max(0, Math.floor(deltaSec));
  if (d < 60) return `${d}s ago`;
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  return `${Math.floor(d / 3600)}h ago`;
}

function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '';
  const dSec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (dSec < 60) return `${dSec} s ago`;
  if (dSec < 3600) return `${Math.floor(dSec / 60)} min ago`;
  if (dSec < 86400) return `${Math.floor(dSec / 3600)} hr ago`;
  return `${Math.floor(dSec / 86400)} d ago`;
}

interface ShapeStatus {
  has_shape: boolean;
  captured_at?: string;
  capture_complete?: boolean;
  offset_verification?: string;
  librosa_version?: number;
  offset_quality?: number;
  needs_recapture?: boolean;
  needs_recapture_reason?: string;
  needs_recapture_flag_count?: number;
  needs_recapture_flagged_at?: string;
  last_attempt?: { status: string; reason?: string } | null;
  last_attempt_global?: {
    for_uri?: string; status?: string; reason?: string; title?: string; artist?: string;
  } | null;
}

interface LedfxHealth {
  breaker_open?: boolean;
  consecutive_failures?: number;
  counters?: Record<string, number>;
  events?: { kind: string; ts: number; count?: number; max_held_ms?: number; detail?: string }[];
  now?: number;
}

export default function DebugPage() {
  ensureLiveState();
  const toast = useToast();
  const qc = useQueryClient();

  const track = useLiveStore((s) => s.track);
  const timing = useLiveStore((s) => s.timing);
  const ledfxRttMs = useLiveStore((s) => s.ledfxRttMs);
  const lastPollAt = useLiveStore((s) => s.lastPollAt);
  const analyzedOverride = useLiveStore((s) => s.analyzedOverride);
  const uri = track?.spotify_uri ?? null;
  const shapeOffsetMs = Number(timing.shape_offset_ms ?? 0);

  const { data: meta } = useAudioShapeMeta(uri);
  const { data: shape } = useAudioShapeData(uri, meta?.capture_complete ?? false);
  const feeds = useDebugFeeds(uri, shapeOffsetMs, shape ?? null);

  // Canvas playhead marks the AUDIBLE moment in saved-shape time — the same
  // correction Now Playing applies: raw progress − audio latency + engine
  // offset − perception trim. The timeline bar keeps raw progress. The shift
  // ref is assigned after the trim query below.
  const { data: settings } = useSettings();
  const playheadShiftRef = useRef(0);
  const getCanvasNowMs = useCallback(() => {
    const now = getLiveProgressMs();
    return now === null ? null : now + playheadShiftRef.current;
  }, []);

  // ── Follow window anchored to the live capture edge (falls back to playhead) ─
  const getAnchor = useCallback((): number | null => {
    const e = feeds.liveEdge.current;
    if (e && Date.now() - e.wallMs < LIVE_EDGE_STALE_MS) return e.ms;
    return getLiveProgressMs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const durationMs = meta?.duration_ms ?? track?.duration_ms ?? 240_000;
  const followWin = useFollowWindow({
    getNowMs: getAnchor,
    durationMs,
    seedWindowS: 10,
    seedFutureS: 2,
    keyPrefix: 'dbg.',
  });

  // Re-enable follow on song change (legacy behavior).
  useEffect(() => {
    if (uri) followWin.setFollow(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uri]);

  // ── Canvas plumbing ────────────────────────────────────────────────────────
  const view: ViewState = useMemo(() => ({
    // Total band only — keeps the saved-vs-live comparison uncluttered.
    filters: { total: true, bass: false, mid: false, high: false, marks: false },
    avgFilters: { total: false, bass: false, mid: false, high: false },
    markFilters: ALL_MARKS,
    librosaFilters: NO_LIBROSA,
    scales: { total: 1, bass: 1, mid: 1, high: 1 },
    scaleOverall: 1,
    offsetMs: 0, // debug draws everything in saved-shape time; live is pre-shifted
    librosaOffsetMs: 0,
    triggerOffsetMs: 0,
    maxRms: null,
    intensityMode: 'off',
    advanced: false,
  }), []);

  const emptyBag = {
    averages: null, meta: null, librosa: null, mfccDistances: null,
    triggers: [], events: [], calibrationTargetsMs: [],
    draggingIntensity: null, selectedIds: [], hoverTriggerId: null,
  };

  const shapeData: LayerDataBag = useMemo(() => ({
    ...emptyBag,
    shape: shape ?? null,
    live: feeds.live,
    spikes: feeds.spikes,
    xcorrWindows: feeds.xcorrWindows,
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [shape, feeds.live, feeds.spikes, feeds.xcorrWindows]);

  const diffData: LayerDataBag = useMemo(() => ({
    ...emptyBag,
    shape: null,
    diff: feeds.diff,
    spikes: feeds.spikes,
    monitorHistory: feeds.monitorHistory,
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [feeds.diff, feeds.spikes, feeds.monitorHistory]);

  // ── Trim ───────────────────────────────────────────────────────────────────
  const { data: trim } = useQuery({
    queryKey: ['perception-trim', uri],
    queryFn: () => apiGet<{ perception_trim_ms: number }>(`/audio-shape/perception-trim?uri=${encodeURIComponent(uri!)}`),
    enabled: !!uri,
    retry: false,
  });
  useEffect(() => onMessage('perception_trim_updated', (msg) => {
    void qc.invalidateQueries({ queryKey: ['perception-trim', msg.uri] });
  }), [qc]);
  playheadShiftRef.current =
    -Number(settings?.audio_latency_ms ?? 0)
    + (timing.shape_offset_ms != null
        ? Number(timing.shape_offset_ms)
        : Number(meta?.timestamp_offset_ms ?? 0))
    - Number(trim?.perception_trim_ms ?? 0);
  const bumpTrim = async (deltaMs: number, reset = false) => {
    if (!uri) return;
    const params = new URLSearchParams({ uri });
    if (reset) params.set('value_ms', '0');
    else params.set('delta_ms', String(deltaMs));
    try {
      await apiPost(`/audio-shape/perception-trim?${params}`);
      void qc.invalidateQueries({ queryKey: ['perception-trim', uri] });
    } catch (e) {
      toast(`Trim failed: ${e instanceof Error ? e.message : e}`, 'error');
    }
  };
  const setTrimAbs = async (valueMs: number) => {
    if (!uri) return;
    const params = new URLSearchParams({ uri, value_ms: String(valueMs | 0) });
    try {
      await apiPost(`/audio-shape/perception-trim?${params}`);
      void qc.invalidateQueries({ queryKey: ['perception-trim', uri] });
    } catch (e) {
      toast(`Trim failed: ${e instanceof Error ? e.message : e}`, 'error');
    }
  };

  // ── Live buffer nudge ([ / ] keys) ─────────────────────────────────────────
  const bufferRef = useRef(0);
  bufferRef.current = Number(timing.buffer_ms ?? bufferRef.current);
  const nudgeBuffer = useCallback(async (delta: number) => {
    const next = bufferRef.current + delta;
    try {
      await api('PATCH', '/settings', { ledfx_trigger_buffer_ms: next });
      bufferRef.current = next;
      toast(`Buffer: ${next} ms`, 'info');
    } catch {
      toast('Nudge failed', 'error');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;
      if (e.key === '[' || e.key === '{') { e.preventDefault(); void nudgeBuffer(-50); }
      if (e.key === ']' || e.key === '}') { e.preventDefault(); void nudgeBuffer(+50); }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [nudgeBuffer]);

  // ── Shape status + LedFX health polls ──────────────────────────────────────
  const { data: shapeStatus, refetch: refetchStatus } = useQuery({
    queryKey: ['shape-status', uri],
    queryFn: () => apiGet<ShapeStatus>(`/audio-shape/status?uri=${encodeURIComponent(uri!)}`),
    enabled: !!uri,
    retry: false,
  });
  // Q updates without reload when a new high-Q lock is applied.
  useEffect(() => onMessage('xcorr_window', (msg) => {
    if (msg.applied && msg.uri === uri) void refetchStatus();
  }), [uri, refetchStatus]);

  const { data: health } = useQuery({
    queryKey: ['ledfx-health'],
    queryFn: () => apiGet<LedfxHealth>('/debug/ledfx-health'),
    refetchInterval: 2000,
  });

  // Poll-age ticker.
  const [pollAge, setPollAge] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setPollAge(lastPollAt ? Date.now() - lastPollAt : 0), 250);
    return () => clearInterval(t);
  }, [lastPollAt]);

  const recapture = async () => {
    if (!uri || !track) { toast('No track loaded', 'error'); return; }
    if (!confirm(`Delete the stored audio shape, WAV, and librosa data for:\n\n${track.title} — ${track.artist}\n\nThe song will re-capture on the next play.`)) return;
    try {
      const r = await fetch(`/api/audio-shape?uri=${encodeURIComponent(uri)}`, { method: 'DELETE' });
      if (!r.ok) throw new Error(await r.text());
      toast('Shape deleted — will re-capture on next play.', 'success');
      void refetchStatus();
    } catch (e) {
      toast(`Delete failed: ${e instanceof Error ? e.message : e}`, 'error');
    }
  };
  const forceNext = async () => {
    try {
      await apiPost('/control/recapture?enabled=true&count=1');
      toast('Force-recapture queued for the next song.', 'success');
    } catch (e) {
      toast(`Failed: ${e instanceof Error ? e.message : e}`, 'error');
    }
  };

  const toggleAnalyzedOverride = async () => {
    try {
      const r = await apiPost<{ analyzed_trigger_override: boolean; has_analyzed: boolean; count: number }>(
        `/control/analyzed-trigger-override?enabled=${!analyzedOverride}`, {});
      if (r.analyzed_trigger_override) {
        toast(r.has_analyzed
          ? `Analyzed override ON — ${r.count} analyzed triggers active`
          : 'Analyzed override ON — no analyzed triggers for this song (no librosa data or no matching training profile)',
          r.has_analyzed ? 'success' : 'error');
      } else {
        toast('Analyzed override OFF — stored triggers active', 'success');
      }
    } catch (e) {
      toast(`Failed: ${e instanceof Error ? e.message : e}`, 'error');
    }
  };

  const liveSpan = feeds.live?.timestamps_ms.length
    ? feeds.live.timestamps_ms[feeds.live.timestamps_ms.length - 1] - feeds.live.timestamps_ms[0]
    : 0;
  const diffStatus = !feeds.live
    ? 'xcorr idle — no live frames'
    : liveSpan < DIFF_MIN_SPAN_MS
      ? `warming up (${(liveSpan / 1000).toFixed(1)}s captured)`
      : `${feeds.live.timestamps_ms.length} bins (25ms) · shifted by ${shapeOffsetMs >= 0 ? '+' : ''}${shapeOffsetMs}ms`;

  const anchorCandidates = (meta?.anchor_candidates ?? []) as {
    timestamp_ms?: number; band?: string; uniqueness?: number; rise_magnitude?: number;
  }[];

  const g = shapeStatus?.last_attempt_global;
  const dur = durationMs;

  return (
    <>
      {/* ── Track header + lock confidence ── */}
      <div className="card">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 10 }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>{track?.title ?? '—'}</div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{track?.artist ?? ''}</div>
          </div>
          <label
            title="Ignore the song's stored triggers and run the analyzed-triggerless pipeline instead — for testing tuned training profiles on songs that already have manual profiles. Now Playing shows the source as “Analyzed Override” while on."
            style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6,
                     fontSize: 12, cursor: 'pointer',
                     color: analyzedOverride ? '#4caf50' : 'var(--text-muted)' }}>
            <input type="checkbox" checked={analyzedOverride}
              onChange={() => void toggleAnalyzedOverride()} />
            Analyzed override
          </label>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'monospace' }}>
            {uri ?? ''}
          </span>
        </div>
        <LockBadge
          monitor={feeds.monitor}
          offsetMs={timing.shape_offset_ms != null ? Number(timing.shape_offset_ms) : null}
          quality={timing.shape_offset_quality != null ? Number(timing.shape_offset_quality) : null}
        />
      </div>

      {/* ── Audio Shape (saved up / live down) ── */}
      <div className="card" style={{ padding: '10px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>Audio Shape</span>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {shape ? `${shape.timestamps_ms.length} samples · duration ${(dur / 1000).toFixed(0)}s`
              : uri ? 'No saved shape for this song.' : 'No song.'}
          </span>
          <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}
              title="Per-track perception trim — layered on top of the xcorr-derived offset. Negative = lighting fires earlier; positive = later.">
              trim
            </span>
            {[-250, -100, -50].map((d) => (
              <button key={d} style={{ fontSize: 11, padding: '2px 6px' }} onClick={() => void bumpTrim(d)}>{d}</button>
            ))}
            <input
              type="number"
              step={50}
              key={`${uri}:${trim?.perception_trim_ms ?? 0}`}
              defaultValue={trim?.perception_trim_ms ?? 0}
              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
              onBlur={(e) => {
                const v = parseInt(e.target.value, 10);
                if (!Number.isNaN(v) && v !== (trim?.perception_trim_ms ?? 0)) void setTrimAbs(v);
              }}
              style={{ width: 64, fontSize: 11, padding: '1px 4px', textAlign: 'center' }}
            />
            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>ms</span>
            {[50, 100, 250].map((d) => (
              <button key={d} style={{ fontSize: 11, padding: '2px 6px' }} onClick={() => void bumpTrim(d)}>+{d}</button>
            ))}
            <button style={{ fontSize: 11, padding: '2px 6px' }} title="Reset to 0" onClick={() => void bumpTrim(0, true)}>×</button>
          </span>
        </div>
        <TimelineCanvas
          layers={SHAPE_LAYERS}
          data={shapeData}
          view={view}
          getWin={followWin.getWin}
          getNowMs={getCanvasNowMs}
          height={240}
          pointer={{
            onPan: (deltaMs) => {
              const w = followWin.getWin();
              followWin.setFollow(false);
              followWin.setManualWin({ startMs: w.startMs + deltaMs, endMs: w.endMs + deltaMs });
            },
          }}
        />
        <div style={{ marginTop: 8 }}>
          <TimelineBar
            durationMs={dur}
            triggers={[]}
            events={[]}
            getWin={followWin.getWin}
            getNowMs={getLiveProgressMs}
            follow={followWin.follow}
            onManualWin={(w) => { followWin.setFollow(false); followWin.setManualWin(w); }}
            onAdjustFollow={(edge, deltaMs) => {
              if (edge === 'end' || edge === 'center') followWin.setFutureS((s) => Math.max(0, s + deltaMs / 1000));
              if (edge === 'start') followWin.setWindowS((s) => Math.max(2, s - deltaMs / 1000));
            }}
            onEdit={() => {}}
            onMove={() => {}}
            onDelete={() => {}}
            onCreate={() => {}}
            onArmedContext={() => {}}
          />
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 6 }}>
          <button className={followWin.follow ? 'primary' : ''} style={{ fontSize: 11, padding: '2px 8px' }}
            title="Follow the live capture edge (falls back to the playhead when xcorr is idle)."
            onClick={() => followWin.setFollowSnapped(!followWin.follow)}>
            {followWin.follow ? 'Follow' : 'Manual'}
          </button>
          <button style={{ fontSize: 11, padding: '2px 8px' }} onClick={followWin.fullSong}>Full Song</button>
          <span style={{ flex: 1 }} />
          <HelpLink topic="debug-shape-canvas" title="How to read this canvas" />
        </div>
      </div>

      {/* ── Diff + rolling-R confidence ── */}
      <CollapsibleCard
        id="dbg-diff"
        title="Live − Saved diff · rolling R"
        headerExtra={
          <span style={{ fontSize: 11, display: 'flex', gap: 10, alignItems: 'center' }}>
            <span style={{ color: 'var(--text-muted)' }}>{diffStatus}</span>
            <HelpLink topic="debug-diff-canvas" title="How to read this canvas" />
          </span>
        }
      >
        <TimelineCanvas
          layers={DIFF_LAYERS}
          data={diffData}
          view={view}
          getWin={followWin.getWin}
          getNowMs={getCanvasNowMs}
          height={240}
          pointer={{
            onPan: (deltaMs) => {
              const w = followWin.getWin();
              followWin.setFollow(false);
              followWin.setManualWin({ startMs: w.startMs + deltaMs, endMs: w.endMs + deltaMs });
            },
          }}
        />
      </CollapsibleCard>

      {/* ── Shape status + recapture ── */}
      <div className="card" style={{ padding: '10px 14px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>Shape status</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
            <button style={{ fontSize: 11, padding: '3px 10px', color: '#f44336', borderColor: '#f44336' }}
              title="Delete the stored audio shape (NPZ + JSON + WAV + librosa) so the song re-captures on next play."
              onClick={() => void recapture()}>
              Recapture
            </button>
            <button style={{ fontSize: 11, padding: '3px 10px' }}
              title="Queue a force-recapture for the next song that plays. Captures over the existing shape atomically."
              onClick={() => void forceNext()}>
              Force-recapture next play
            </button>
          </span>
        </div>
        <div className="dbg-grid" style={{ gridTemplateColumns: '120px 1fr' }}>
          <span>Captured</span>
          <span style={{ color: shapeStatus?.has_shape && shapeStatus.captured_at ? undefined : 'var(--text-muted)' }}>
            {!shapeStatus ? '—'
              : !shapeStatus.has_shape ? 'no shape captured'
                : shapeStatus.captured_at
                  ? `${new Date(shapeStatus.captured_at).toLocaleString()} (${fmtRelative(shapeStatus.captured_at)})`
                  : 'unknown'}
          </span>
          <span>State</span>
          <span>
            {shapeStatus?.has_shape
              ? [
                  shapeStatus.capture_complete ? 'complete' : 'incomplete',
                  shapeStatus.offset_verification,
                  `librosa v${shapeStatus.librosa_version}`,
                  ...(shapeStatus.offset_quality && shapeStatus.offset_quality > 0
                    ? [`Q=${shapeStatus.offset_quality.toFixed(2)}`] : []),
                ].join(' · ')
              : '—'}
          </span>
          <span>Needs recapture</span>
          <span style={{ color: shapeStatus?.needs_recapture ? '#f44336' : undefined }}>
            {!shapeStatus?.has_shape ? '—'
              : shapeStatus.needs_recapture
                ? `yes — ${shapeStatus.needs_recapture_reason || '(no reason)'} · flag count ${shapeStatus.needs_recapture_flag_count}` +
                  (shapeStatus.needs_recapture_flagged_at ? ` · flagged ${fmtRelative(shapeStatus.needs_recapture_flagged_at)}` : '')
                : 'no'}
          </span>
          <span>Last attempt</span>
          <span style={{
            color: shapeStatus?.last_attempt
              ? shapeStatus.last_attempt.status === 'ok' ? '#4caf50' : '#f44336'
              : 'var(--text-muted)',
          }}>
            {shapeStatus?.last_attempt
              ? shapeStatus.last_attempt.status === 'ok'
                ? '✓ ok (this URI)'
                : `✗ failed: ${shapeStatus.last_attempt.reason || 'unknown'} (this URI)`
              : 'idle (no recent attempt for this URI)'}
          </span>
          <span>Previous attempt</span>
          <span style={{
            color: g && g.for_uri && g.for_uri !== uri
              ? g.status === 'ok' ? '#4caf50' : '#f44336'
              : 'var(--text-muted)',
          }}>
            {g && g.for_uri && g.for_uri !== uri
              ? `${g.status === 'ok' ? '✓' : '✗'} ${g.artist ? `${g.artist} — ` : ''}${g.title || g.for_uri}: ${g.status === 'ok' ? 'capture ok' : g.reason || 'failed'}`
              : '—'}
          </span>
        </div>
      </div>

      {/* ── Sync state ── */}
      <div className="card" style={{ padding: '10px 14px' }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Sync state</div>
        <div className="dbg-grid">
          <span>Buffer</span><span>{timing.buffer_ms ?? '—'}</span><span style={{ opacity: 0.5 }}>ms (manual setting)</span>
          <span>RTT</span><span>{ledfxRttMs != null ? Math.round(ledfxRttMs) : '—'}</span><span style={{ opacity: 0.5 }}>ms (LedFX network)</span>
          <span>Shape</span><span>{timing.shape_offset_ms ?? '—'}</span>
          <span style={{ opacity: 0.5 }}>
            {timing.shape_offset_quality != null ? `ms (Q=${Number(timing.shape_offset_quality).toFixed(2)})` : 'ms (per-song xcorr)'}
          </span>
          <b>Total offset</b><b>{timing.effective_offset_ms ?? '—'}</b><span style={{ opacity: 0.5 }}>ms — positive fires earlier</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
          <span style={{ opacity: 0.7, fontSize: 12 }}>Live nudge:</span>
          <button style={{ fontSize: 11, padding: '2px 8px' }} onClick={() => void nudgeBuffer(-50)}>−50 ms</button>
          <span style={{ fontWeight: 600, minWidth: 60, textAlign: 'center', fontSize: 12 }}>{timing.buffer_ms ?? '—'} ms</span>
          <button style={{ fontSize: 11, padding: '2px 8px' }} onClick={() => void nudgeBuffer(+50)}>+50 ms</button>
          <span style={{ opacity: 0.5, fontSize: 11 }}>[ / ] keys</span>
        </div>
      </div>

      {/* ── LedFX load governor ── */}
      <div className="card" style={{ padding: '10px 14px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>LedFX load</span>
          <span style={{
            fontSize: 10, fontWeight: 600, padding: '1px 8px', borderRadius: 10,
            background: health?.breaker_open ? '#3a1b1b' : (health?.consecutive_failures ?? 0) > 0 ? '#3a331b' : '#1b3a1b',
            color: health?.breaker_open ? '#ff5252' : (health?.consecutive_failures ?? 0) > 0 ? '#ffb300' : '#00ff88',
          }}>
            {health?.breaker_open ? 'CIRCUIT OPEN'
              : (health?.consecutive_failures ?? 0) > 0 ? `${health!.consecutive_failures} fail` : 'OK'}
          </span>
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>
          held {health?.counters?.held ?? 0} · shed {health?.counters?.shed ?? 0} · trips {health?.counters?.breaker_open ?? 0}
          {' '}· recycled {health?.counters?.recycled ?? 0} · recovered {health?.counters?.recovered ?? 0}
        </div>
        <div className="dbg-mono" style={{ maxHeight: 160, whiteSpace: 'normal' }}>
          {!health?.events?.length && 'no load-shed events'}
          {health?.events?.map((ev, i) => {
            const st = LEDFX_EVENT_STYLE[ev.kind] ?? { label: ev.kind.toUpperCase(), color: '#aaa' };
            return (
              <div key={i}>
                <span style={{ color: st.color, fontWeight: 600 }}>
                  {st.label}{ev.count && ev.count > 1 ? ` ×${ev.count}` : ''}
                </span>
                <span style={{ opacity: 0.55 }}>
                  {ev.max_held_ms != null ? ` (${Math.round(ev.max_held_ms)}ms wait)` : ''}
                  {ev.detail ? ` ${ev.detail}` : ''} · {agoStr((health.now ?? 0) - ev.ts)}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Last trigger ── */}
      <div className="card" style={{ padding: '10px 14px', fontSize: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Last trigger</div>
        <span style={{ opacity: 0.7 }}>Event:</span>
        <span style={{ marginLeft: 8 }}>{feeds.lastFire?.event_name ?? feeds.lastFire?.trigger_id ?? '—'}</span>
        {feeds.lastFire?.scheduled_ms != null && (
          <div style={{ marginTop: 4, fontFamily: 'monospace', fontSize: 11, opacity: 0.8 }}>
            scheduled {feeds.lastFire.scheduled_ms}ms · fired {feeds.lastFire.fired_at_ms}ms ·{' '}
            Δ {(feeds.lastFire.fired_at_ms ?? 0) - (feeds.lastFire.scheduled_ms ?? 0) >= 0 ? '+' : ''}
            {(feeds.lastFire.fired_at_ms ?? 0) - (feeds.lastFire.scheduled_ms ?? 0)}ms ·{' '}
            effective_offset {feeds.lastFire.effective_offset_ms ?? '—'}ms
          </div>
        )}
        <div style={{ marginTop: 4 }}>Poll age: {pollAge} ms</div>
      </div>

      {/* ── Anchor snap ── */}
      <div className="card" style={{ padding: '10px 14px' }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Anchor snap</div>
        <div className="dbg-mono">
          {!anchorCandidates.length
            ? 'no anchor candidates for this song'
            : `${anchorCandidates.length} candidates\n` + anchorCandidates.map((c, i) =>
                `  #${i + 1}  ${String(c.timestamp_ms ?? 0).padStart(6)}ms  ` +
                `${(c.band ?? '').replace('rms_', '').padEnd(5)}  ` +
                `u=${Number(c.uniqueness ?? 0).toFixed(2)}  rise=${Number(c.rise_magnitude ?? 0).toFixed(2)}`,
              ).join('\n')}
        </div>
        {feeds.anchorMatch && (
          <div style={{ marginTop: 4, fontFamily: 'monospace', fontSize: 11, color: '#00ff88' }}>
            {feeds.anchorMatch.source === 'anchor' ? 'Anchor matched: ' : 'live match: '}
            cand #{feeds.anchorMatch.candidate_idx + 1} ({feeds.anchorMatch.band.replace('rms_', '')}) →{' '}
            {feeds.anchorMatch.offset_ms >= 0 ? '+' : ''}{feeds.anchorMatch.offset_ms}ms{' '}
            r={feeds.anchorMatch.r.toFixed(2)} Q={feeds.anchorMatch.q.toFixed(2)}
          </div>
        )}
      </div>

      {/* ── Per-window xcorr ── */}
      <div className="card" style={{ padding: '10px 14px' }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Per-window xcorr (this play)</div>
        <div className="dbg-mono">{feeds.xcorrLines.length ? feeds.xcorrLines.join('\n') : 'no windows yet'}</div>
      </div>

      {/* ── Mismatch spikes ── */}
      <div className="card" style={{ padding: '10px 14px' }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
          Mismatch spikes <span style={{ color: '#ff2d95' }}>●</span> (recovery windows)
        </div>
        <div className="dbg-mono" style={{ color: feeds.spikeLines.length ? '#ff2d95' : undefined }}>
          {feeds.spikeLines.length ? feeds.spikeLines.join('\n') : 'no spikes yet'}
        </div>
      </div>
    </>
  );
}
