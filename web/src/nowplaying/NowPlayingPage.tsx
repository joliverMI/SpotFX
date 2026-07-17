/** Now Playing — the listener view (port of frontend/index.html).
 * Reuses the builder's TimelineCanvas + layers for the audio shape; debug
 * widgets (trim, nudge, sync panels) live on /debug. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from '../api/client';
import { onMessage } from '../api/ws';
import { useEvents, useSettings } from '../api/queries';
import {
  useAudioShapeData, useAudioShapeMeta, useLibrosa,
} from '../builder/queries';
import TimelineCanvas from '../builder/canvas/TimelineCanvas';
import {
  avgLines, beatStrips, diamonds, librosaOverlays, musicMarks, playhead, rmsBands, triggers as triggersLayer,
} from '../builder/canvas/layers';
import { BEAT_STRIP_H, stripCountFor, type LayerDataBag, type ViewState } from '../builder/canvas/frame';
import { computeAverages, computeMfccDistances } from '../builder/canvas/data';
import { useFollowWindow } from '../builder/hooks/useFollowWindow';
import CollapsibleCard from '../components/CollapsibleCard';
import { useToast } from '../components/Toast';
import { fmtCountdown, fmtMs } from '../lib/time';
import { ensureLiveState, getLiveProgressMs, useLiveStore, useLiveTick } from '../live/liveStore';
import TriggerListCard from './TriggerListCard';
import { SOURCE_BADGE, useNowProfile } from './useNowProfile';
import type { MarkType, MusicTrigger } from '../builder/types';

const ALL_MARKS: Record<MarkType, boolean> = {
  bass_drop: true, bass_start: true, bass_end: true, power_up: true,
  power_down: true, quiet: true, charging: true, tempo_change: true,
};

const NP_LAYERS = [rmsBands, avgLines, diamonds, librosaOverlays, musicMarks, triggersLayer, playhead, beatStrips];

interface PreviewRow {
  tag: string;      // lane / child-event name ("Shape", "Color", …)
  scope: string;    // device categories / roles / virtual ids
  text: string;     // capped change description ("twist → 4, blur +0.3")
  full: string;     // uncapped description for the tooltip ('' = same as text)
  colors: string[]; // hex swatches referenced by the change
  at_ms: number;    // fire offset relative to the trigger point
}

interface NextPreview {
  trigger_id: string;
  event_name: string;
  event_color?: string;
  action_label?: string;
  rows?: PreviewRow[];
}

const BOARD_ROWS = 3; // rows shown on the next-changes board (fixed height)

function fmtAt(atMs: number): string {
  return `${atMs > 0 ? '+' : '−'}${(Math.abs(atMs) / 1000).toFixed(1)}s`;
}

export default function NowPlayingPage() {
  ensureLiveState();
  const toast = useToast();
  const qc = useQueryClient();

  const track = useLiveStore((s) => s.track);
  const paused = useLiveStore((s) => s.paused);
  const onTargetDevice = useLiveStore((s) => s.onTargetDevice);
  const recordingActive = useLiveStore((s) => s.recordingActive);
  const lastCapture = useLiveStore((s) => s.lastCapture);
  const dinnerParty = useLiveStore((s) => s.dinnerParty);
  const ambient = useLiveStore((s) => s.ambient);
  const useAnalyzed = useLiveStore((s) => s.useAnalyzed);
  const lastScene = useLiveStore((s) => s.lastScene);
  const lastColorSet = useLiveStore((s) => s.lastColorSet);
  const ledfxRttMs = useLiveStore((s) => s.ledfxRttMs);
  const timing = useLiveStore((s) => s.timing);
  const nextTrackUri = useLiveStore((s) => s.nextTrackUri);

  const uri = track?.spotify_uri ?? null;
  const progressMs = useLiveTick(250);

  const { data: authStatus } = useQuery({
    queryKey: ['auth-status'],
    queryFn: () => apiGet<{ authenticated: boolean }>('/spotify/auth-status'),
    staleTime: 60_000,
  });

  const { triggers, source } = useNowProfile(uri);
  const { data: settings } = useSettings();
  const { data: events } = useEvents();
  const { data: meta } = useAudioShapeMeta(uri);
  const { data: shape } = useAudioShapeData(uri, meta?.capture_complete ?? false);
  const { data: librosa } = useLibrosa(uri);
  const { data: trim } = useQuery({
    queryKey: ['perception-trim', uri],
    queryFn: () => apiGet<{ perception_trim_ms: number }>(`/audio-shape/perception-trim?uri=${encodeURIComponent(uri!)}`),
    enabled: !!uri,
    retry: false,
  });

  // Prefetch the next song's shape so the swap on track change is instant
  // (replaces the legacy double-buffered canvas).
  useEffect(() => {
    if (!nextTrackUri || nextTrackUri === uri) return;
    const enc = encodeURIComponent(nextTrackUri);
    void qc.prefetchQuery({ queryKey: ['shape-meta', nextTrackUri], queryFn: () => apiGet(`/audio-shape/meta?uri=${enc}`), staleTime: 60_000 });
    void qc.prefetchQuery({ queryKey: ['shape-data', nextTrackUri], queryFn: () => apiGet(`/audio-shape/data?uri=${enc}`), staleTime: 5 * 60_000 });
    void qc.prefetchQuery({ queryKey: ['librosa', nextTrackUri], queryFn: () => apiGet(`/audio-shape/librosa?uri=${enc}`), staleTime: 5 * 60_000 });
  }, [nextTrackUri, uri, qc]);

  // ── Fired / preview state ──────────────────────────────────────────────────
  const [lastFiredIdx, setLastFiredIdx] = useState(-1);
  const [resolvedActions, setResolvedActions] = useState<Record<string, string>>({});
  const [nextPreview, setNextPreview] = useState<NextPreview | null>(null);
  const [follow, setFollow] = useState(true);
  const [flash, setFlash] = useState<{ color: string; id: string | null } | null>(null);
  const [morphSummary, setMorphSummary] = useState<string | null>(null);
  const pendingLabels = useRef<Record<string, string>>({});
  const triggersRef = useRef(triggers);
  triggersRef.current = triggers;

  // Starting offset for the "start X → now Y" status (reset per song).
  const startOffset = useRef<{ uri: string; offset: number; q: number | null } | null>(null);

  useEffect(() => {
    // Track change: reset fired/preview state.
    setLastFiredIdx(-1);
    setResolvedActions({});
    setNextPreview(null);
    setFollow(true);
    pendingLabels.current = {};
    startOffset.current = null;
  }, [uri]);

  useEffect(() => {
    const offs = [
      onMessage('trigger_fired', (msg) => {
        const color = String(msg.color ?? '#FFD700');
        const tid = String(msg.trigger_id ?? '');
        setFlash({ color, id: tid });
        setTimeout(() => setFlash(null), 500);
        if (msg.summary && (msg.event_type === 'morph_set' || msg.event_type === 'composite' || msg.event_type === undefined)) {
          setMorphSummary(String(msg.summary));
          setTimeout(() => setMorphSummary(null), 2500);
        }
        const stored = pendingLabels.current[tid];
        if (stored) {
          setResolvedActions((m) => ({ ...m, [tid]: stored }));
          delete pendingLabels.current[tid];
        }
        const idx = triggersRef.current.findIndex((t) => t.id === tid);
        if (idx >= 0) setLastFiredIdx(idx);
        setNextPreview((p) => (p?.trigger_id === tid ? null : p));
      }),
      onMessage('trigger_preview', (msg) => {
        const p = msg as unknown as NextPreview;
        if (p.action_label) pendingLabels.current[p.trigger_id] = p.action_label;
        setNextPreview(p);
      }),
      onMessage('trigger_preview_clear', () => setNextPreview(null)),
      onMessage('auto_generate_started', (msg) =>
        toast(`Generating AI triggers for ${msg.artist} — ${msg.title}…`, 'info')),
      onMessage('auto_generate_complete', (msg) =>
        toast(`AI triggers ready: ${msg.count} suggestions for ${msg.artist} — ${msg.title}`, 'success')),
      onMessage('auto_generate_failed', (msg) =>
        toast(`Auto-gen failed for ${msg.title}: ${msg.error}`, 'error')),
    ];
    return () => offs.forEach((off) => off());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Shape status: "start X → now Y" ────────────────────────────────────────
  const shapeOffset = timing.shape_offset_ms;
  const shapeQ = timing.shape_offset_quality;
  if (uri && shapeOffset != null && (startOffset.current === null || startOffset.current.uri !== uri)) {
    startOffset.current = { uri, offset: shapeOffset, q: shapeQ ?? null };
  }
  const fmtOff = (o: number, q: number | null | undefined) =>
    `${o >= 0 ? '+' : ''}${o}ms${q && q > 0 ? ` Q=${q.toFixed(2)}` : ''}`;

  // Recapture-suggested badge: ≥3 consecutive anti-correlated plays on the
  // active Set List slot.
  const { data: offsetStats } = useQuery({
    queryKey: ['auto-offset-stats', uri],
    queryFn: () => apiGet<{ setlist_offsets?: Record<string, { anti_corr_count?: number }> }>(
      `/audio-shape/auto-offset-stats?uri=${encodeURIComponent(uri!)}`),
    enabled: !!uri,
    retry: false,
  });
  const antiCorrCount = (() => {
    const slId = timing.active_setlist_id;
    const slot = slId ? offsetStats?.setlist_offsets?.[slId] : null;
    return slot ? Number(slot.anti_corr_count ?? 0) : 0;
  })();

  // ── Canvas plumbing (reuses the builder stack) ─────────────────────────────
  const audioLatencyRef = useRef(0);
  audioLatencyRef.current = Number(settings?.audio_latency_ms ?? 0);
  const getCanvasNowMs = useCallback(() => {
    const now = getLiveProgressMs();
    return now === null ? null : now - audioLatencyRef.current;
  }, []);
  const durationMs = track?.duration_ms || meta?.duration_ms || 1;
  const followWin = useFollowWindow({
    getNowMs: getLiveProgressMs,
    durationMs,
    seedWindowS: settings ? Number(settings.builder_zoom_window_s ?? 20) : undefined,
    seedFutureS: settings ? Number(settings.builder_future_buffer_s ?? 5) : undefined,
    keyPrefix: 'np.',
  });
  // Live view: always resume following on page open and track change. Follow
  // is sticky but manual bounds are not, so a persisted follow=false from a
  // past pan would otherwise open the page zoomed out to the full song.
  const { setFollow: setWinFollow, setManualWin: setWinManual } = followWin;
  useEffect(() => {
    setWinFollow(true);
    setWinManual(null);
  }, [uri, setWinFollow, setWinManual]);

  const canvasTriggers: MusicTrigger[] = useMemo(
    () => triggers.map((t) => ({
      id: t.id, timestamp_ms: t.timestamp_ms, event_id: t.event_id,
      labels: t.labels, enabled: true, intensity: 0.5,
    })),
    [triggers],
  );
  const averages = useMemo(
    () => (shape ? computeAverages(shape, Number(settings?.shape_average_window_ms ?? 4000)) : null),
    [shape, settings],
  );
  const mfccDistances = useMemo(() => computeMfccDistances(librosa ?? null), [librosa]);
  const maxRms = useMemo(() => (shape ? Math.max(...shape.rms_total, 1e-9) : null), [shape]);

  const view: ViewState = useMemo(() => ({
    filters: { total: true, bass: true, mid: true, high: true, marks: true },
    avgFilters: { total: false, bass: false, mid: false, high: false },
    markFilters: ALL_MARKS,
    librosaFilters: { sections: true, beats: true, onsets: false, harmonic: false, bass: false, snare: false, mfcc: true },
    scales: {
      total: Number(settings?.shape_scale_total ?? 1), bass: Number(settings?.shape_scale_bass ?? 1),
      mid: Number(settings?.shape_scale_mid ?? 1), high: Number(settings?.shape_scale_high ?? 1),
    },
    scaleOverall: Number(settings?.shape_scale_overall ?? 1),
    // The engine's xcorr baseline (median of saves, minus the perception trim)
    // shifts the playhead — legacy _engineXcorrOffsetMs().
    offsetMs: (shapeOffset ?? meta?.timestamp_offset_ms ?? 0) - (trim?.perception_trim_ms ?? 0),
    librosaOffsetMs: Number((librosa as { librosa_offset_ms?: number } | undefined)?.librosa_offset_ms ?? 0),
    triggerOffsetMs: 0,
    maxRms,
    intensityMode: 'off',
    advanced: false,
  }), [settings, shapeOffset, meta, trim, librosa, maxRms]);

  const data: LayerDataBag = useMemo(() => ({
    shape: shape ?? null,
    averages,
    meta: meta ?? null,
    librosa: librosa ?? null,
    mfccDistances,
    triggers: canvasTriggers,
    events: (events ?? []).map((e) => ({ id: e.id, name: e.name, color: e.color })),
    calibrationTargetsMs: [],
    draggingIntensity: null,
    selectedIds: [],
    hoverTriggerId: null,
  }), [shape, averages, meta, librosa, mfccDistances, canvasTriggers, events]);

  const stripCount = stripCountFor(data, view.librosaFilters);

  // ── Derived UI bits ────────────────────────────────────────────────────────
  const upcoming = useMemo(() => {
    if (progressMs == null) return null;
    return triggers.find((t) => t.timestamp_ms > progressMs) ?? null;
  }, [triggers, progressMs]);

  const service = paused
    ? { label: 'Paused', cls: 'badge-yellow' }
    : !track || !track.is_playing
      ? { label: 'Idle', cls: 'badge-gray' }
      : !onTargetDevice
        ? { label: `Wrong Device: ${track.device_name ?? '?'}`, cls: 'badge-red' }
        : dinnerParty
          ? { label: 'Dinner Party', cls: 'badge-yellow' }
          : { label: 'Active', cls: 'badge-green' };

  const srcBadge = SOURCE_BADGE[source];

  const recapture = async () => {
    if (!uri || !track) return;
    if (!confirm(`Delete the stored audio shape, WAV, and librosa data for:\n\n${track.title} — ${track.artist}\n\nThe song will re-capture on the next play.`)) return;
    try {
      const r = await fetch(`/api/audio-shape?uri=${encodeURIComponent(uri)}`, { method: 'DELETE' });
      if (!r.ok) throw new Error(await r.text());
      toast('Shape deleted — will re-capture on next play.', 'success');
    } catch (e) {
      toast(`Delete failed: ${e instanceof Error ? e.message : e}`, 'error');
    }
  };

  return (
    <>
      {authStatus && !authStatus.authenticated && (
        <div className="card" style={{ borderColor: '#e74c3c', background: '#1a0a0a' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontSize: 20 }}>🔑</span>
            <div>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>Spotify not connected</div>
              <a href="/api/spotify/login" style={{ fontSize: 13, color: '#1db954', fontWeight: 600 }}>
                Click here to authorize Spotify →
              </a>
            </div>
          </div>
        </div>
      )}

      {/* ── Now Playing ── */}
      <div className="card">
        <div className="card-title">Now Playing</div>
        <div style={{ fontSize: 18, fontWeight: 600 }}>{track?.title ?? '—'}</div>
        <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          {track ? (track.artist.length > 40 ? `${track.artist.slice(0, 40)}…` : track.artist) : ''}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
          {(track?.genres ?? []).join(' · ')}
        </div>
        <div style={{ marginTop: 4, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {track?.device_name && (
            <span className={`badge ${onTargetDevice ? 'badge-green' : 'badge-red'}`}
              style={{ fontSize: 10, padding: '1px 7px' }}>
              ▶ on {track.device_name}
            </span>
          )}
          {recordingActive && (
            <span className="badge badge-yellow" style={{ fontSize: 10, padding: '1px 7px' }}>● Recording Audio</span>
          )}
          {!recordingActive && lastCapture?.uri === uri && lastCapture?.status === 'ok' && (
            <span className="badge badge-green" style={{ fontSize: 10, padding: '1px 7px' }}>✓ Recorded</span>
          )}
          {!recordingActive && lastCapture?.uri === uri && lastCapture?.status === 'failed' && (
            <span className="badge badge-red" style={{ fontSize: 10, padding: '1px 7px' }}
              title={(lastCapture.reason ?? 'failed').replace(/_/g, ' ')}>
              ✗ Capture failed
            </span>
          )}
        </div>
      </div>

      {/* ── Controls ── */}
      <div className="card">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <button className={`toggle-btn ${!paused ? 'active' : ''}`}
            title="Activate / pause trigger firing"
            onClick={() => void apiPost(paused ? '/control/resume' : '/control/pause')}>
            Activate
          </button>
          <button className={`toggle-btn ${dinnerParty ? 'active' : ''}`}
            title="Ignore song triggers, use automatic ambient lighting"
            onClick={() => void apiPost(`/control/dinner-party?enabled=${!dinnerParty}`)}>
            Dinner Party
          </button>
          <button className={`toggle-btn ${ambient ? 'active' : ''}`}
            title="Hold the configured devices at a static full-brightness color (Hue REST) and skip them in triggers"
            onClick={() => void apiPost(`/control/ambient-mode?enabled=${!ambient}`)}>
            Ambient
          </button>
          <button className={`toggle-btn ${useAnalyzed ? 'active' : ''}`}
            title="Use analyzed triggers for songs without user triggers"
            onClick={() => void apiPost(`/control/use-analyzed-triggerless?enabled=${!useAnalyzed}`)}>
            Analyzed
          </button>
          {srcBadge && (
            <span style={{
              fontSize: 11, padding: '2px 8px', borderRadius: 10, fontWeight: 600,
              color: srcBadge.color, border: `1px solid ${srcBadge.color}`,
              background: `${srcBadge.color}26`,
            }}>
              {srcBadge.label}
            </span>
          )}
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
            {morphSummary && (
              <span style={{
                fontSize: 11, color: 'var(--accent)', background: 'rgba(33,150,243,0.12)',
                padding: '2px 8px', borderRadius: 10, maxWidth: '60vw',
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {morphSummary}
              </span>
            )}
            <span style={{
              width: 16, height: 16, borderRadius: '50%', display: 'inline-block',
              border: '2px solid var(--border)',
              background: flash ? flash.color : 'transparent',
              boxShadow: flash ? `0 0 12px ${flash.color}` : 'none',
              transition: 'background 0.05s, box-shadow 0.05s',
            }} />
            <span style={{
              fontSize: 28, fontWeight: 700, fontVariantNumeric: 'tabular-nums',
              color: 'var(--accent2)', letterSpacing: '-0.02em', minWidth: 70, textAlign: 'right',
            }}>
              {upcoming && progressMs != null ? fmtCountdown(upcoming.timestamp_ms - progressMs) : ''}
            </span>
          </div>
        </div>
        {(lastScene || lastColorSet) && (
          <div style={{ display: 'flex', marginTop: 8, gap: 16, alignItems: 'center', fontSize: 11, color: 'var(--text-muted)', flexWrap: 'wrap' }}>
            {lastScene && (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                Scene:
                <span style={{ width: 9, height: 9, borderRadius: '50%', background: lastScene.color, display: 'inline-block' }} />
                <span style={{ fontWeight: 600, color: 'var(--text)' }}>{lastScene.name}</span>
              </span>
            )}
            {lastColorSet && (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                Color:
                <span style={{ width: 9, height: 9, borderRadius: '50%', background: lastColorSet.color, display: 'inline-block' }} />
                <span style={{ fontWeight: 600, color: 'var(--text)' }}>{lastColorSet.name}</span>
              </span>
            )}
          </div>
        )}
        {/* Next-changes board — fixed height so the card never jumps. Shows
            the locked-in plan for the next trigger: one row per lane/pick
            (what parameters change and to what). */}
        {(() => {
          const rows = nextPreview?.rows ?? [];
          const shown = rows.slice(0, BOARD_ROWS);
          const extra = rows.length - shown.length;
          return (
            <div style={{
              visibility: nextPreview ? 'visible' : 'hidden', marginTop: 8,
              height: 'calc(1.4em * 4 + 10px)', overflow: 'hidden',
              border: '1px solid var(--border)', borderRadius: 6, padding: '3px 8px',
              background: 'var(--surface2)',
            }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, lineHeight: 1.4 }}>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Next</span>
                <span style={{
                  fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden',
                  textOverflow: 'ellipsis', color: nextPreview?.event_color ?? 'var(--text)',
                }}>
                  {nextPreview?.event_name}
                </span>
                {extra > 0 && (
                  <span title={rows.map((r) => `${r.tag ? `${r.tag}: ` : ''}${r.full || r.text}`).join('\n')}
                    style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto' }}>
                    +{extra} more
                  </span>
                )}
              </div>
              {shown.length > 0 ? shown.map((r, i) => (
                <div key={i} title={`${r.tag ? `${r.tag} ` : ''}${r.scope ? `(${r.scope}) ` : ''}— ${r.full || r.text}`}
                  style={{ display: 'flex', alignItems: 'baseline', gap: 8, lineHeight: 1.4, minWidth: 0 }}>
                  {r.tag && (
                    <span style={{
                      fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em',
                      color: 'var(--accent2)', whiteSpace: 'nowrap', flex: '0 1 auto', maxWidth: '35%',
                      overflow: 'hidden', textOverflow: 'ellipsis',
                    }}>
                      {r.tag}{r.at_ms !== 0 && <span style={{ fontWeight: 400, color: 'var(--text-muted)' }}> {fmtAt(r.at_ms)}</span>}
                    </span>
                  )}
                  {r.scope && (
                    <span style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap', flex: '0 1 auto', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {r.scope}
                    </span>
                  )}
                  <span style={{
                    fontSize: 12, color: 'var(--text)', fontFamily: 'monospace', flex: '1 1 0', minWidth: 0,
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                  }}>
                    {r.text}
                  </span>
                  {r.colors.length > 0 && (
                    <span style={{ display: 'inline-flex', gap: 3, flex: '0 0 auto', alignSelf: 'center' }}>
                      {r.colors.map((c, j) => (
                        <span key={j} style={{
                          width: 9, height: 9, borderRadius: '50%', background: c,
                          border: '1px solid var(--border)', display: 'inline-block',
                        }} />
                      ))}
                    </span>
                  )}
                </div>
              )) : nextPreview?.action_label && (
                // Fallback for previews without structured rows.
                <span title={nextPreview.action_label} style={{
                  fontSize: 12, color: 'var(--text-muted)', fontFamily: 'monospace',
                  display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical',
                  overflow: 'hidden', lineHeight: 1.4, wordBreak: 'break-word',
                }}>
                  {nextPreview.action_label}
                </span>
              )}
            </div>
          );
        })()}
      </div>

      {/* ── Song Timeline ── */}
      <div className="card">
        <div className="card-title">Song Timeline</div>
        <div style={{ position: 'relative', height: 8, background: 'var(--surface2)', borderRadius: 4, marginTop: 8 }}>
          <div style={{
            height: '100%', background: 'var(--accent)', borderRadius: 4,
            width: track && progressMs != null ? `${Math.min(100, (progressMs / track.duration_ms) * 100)}%` : 0,
            transition: 'width 0.25s linear',
          }} />
          {track && triggers.map((t) => (
            <div key={t.id} title={`${t.name} @ ${fmtMs(t.timestamp_ms)}`} style={{
              position: 'absolute', top: -6, width: 3, height: 20, borderRadius: 2,
              transform: 'translateX(-50%)',
              left: `${(t.timestamp_ms / track.duration_ms) * 100}%`,
              background: t.color,
            }} />
          ))}
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
          <span>{fmtMs(progressMs ?? 0)}</span>
          <span>{track && progressMs != null ? `-${fmtMs(track.duration_ms - progressMs)}` : ''}</span>
          <span>{fmtMs(track?.duration_ms ?? 0)}</span>
        </div>
      </div>

      {/* ── Audio Shape ── */}
      <CollapsibleCard
        id="np-shape"
        title="Audio Shape"
        headerExtra={
          <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11 }}>
            {antiCorrCount >= 3 && (
              <span style={{ fontWeight: 600, background: '#9c4a00', color: '#fff', padding: '2px 8px', borderRadius: 10, cursor: 'help' }}
                title="The stored offset for this song is anti-correlated with live audio across multiple plays. Recapturing typically fixes this.">
                recapture suggested ({antiCorrCount} drifts)
              </span>
            )}
            <span style={{ color: 'var(--text-muted)' }}>
              {shapeOffset == null ? (shape ? '' : uri ? 'No audio shape for this song' : '')
                : startOffset.current && startOffset.current.uri === uri && startOffset.current.offset !== shapeOffset
                  ? `start ${fmtOff(startOffset.current.offset, startOffset.current.q)} → now ${fmtOff(shapeOffset, shapeQ)}`
                  : fmtOff(shapeOffset, shapeQ)}
            </span>
            <button style={{ fontSize: 11, padding: '2px 8px', color: '#f44336', borderColor: '#f44336' }}
              title="Delete the stored audio shape (NPZ + WAV + librosa + sidecar) so the song re-captures on next play."
              onClick={(e) => { e.stopPropagation(); void recapture(); }}>
              Recapture
            </button>
          </span>
        }
      >
        <TimelineCanvas
          layers={NP_LAYERS}
          data={data}
          view={view}
          getWin={followWin.getWin}
          getNowMs={getCanvasNowMs}
          height={250 + stripCount * BEAT_STRIP_H}
          pointer={{
            onPan: (deltaMs) => {
              const w = followWin.getWin();
              followWin.setFollow(false);
              followWin.setManualWin({ startMs: w.startMs + deltaMs, endMs: w.endMs + deltaMs });
            },
          }}
        />
        {!followWin.follow && (
          <button style={{ fontSize: 11, padding: '2px 10px', marginTop: 6 }}
            onClick={() => followWin.setFollowSnapped(true)}>
            Follow playhead
          </button>
        )}
      </CollapsibleCard>

      {/* ── Trigger list ── */}
      <TriggerListCard
        triggers={triggers}
        lastFiredIdx={lastFiredIdx}
        nextTriggerId={upcoming?.id ?? null}
        resolvedActions={resolvedActions}
        follow={follow}
        setFollow={setFollow}
        flashId={flash?.id ?? null}
      />

      {/* ── Status bar ── */}
      <div style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        <span>LedFX RTT: {ledfxRttMs ?? '—'} ms</span>
        <span>Offset: {timing.effective_offset_ms ?? '—'} ms</span>
        <span>Service: <span className={`badge ${service.cls}`}>{service.label}</span></span>
      </div>
    </>
  );
}
