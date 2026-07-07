/** AI Triggers review panel: audio-shape canvas with draggable suggestion
 * markers (reuses the builder's TimelineCanvas/layers), band + librosa filter
 * chips, zoom bar, and the suggestion review list. */
import { useCallback, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from '../api/client';
import { useSettings } from '../api/queries';
import { useAudioShapeData, useAudioShapeMeta, useLibrosa } from '../builder/queries';
import TimelineCanvas, { type FrameGeom } from '../builder/canvas/TimelineCanvas';
import TimelineBar from '../builder/components/TimelineBar';
import { avgLines, beatStrips, diamonds, librosaOverlays, musicMarks, playhead, rmsBands } from '../builder/canvas/layers';
import { computeAverages, computeMfccDistances, snapTimestamp } from '../builder/canvas/data';
import type { Hit, LayerDataBag, ViewState } from '../builder/canvas/frame';
import { useFollowWindow } from '../builder/hooks/useFollowWindow';
import type { EventOption, MarkType } from '../builder/types';
import { getLiveProgressMs, useLiveStore } from '../live/liveStore';
import { aiMarkers } from './markerLayer';
import SuggestionRow from './SuggestionRow';
import { markerColor, type CachedSet, type Suggestion } from './types';

const ALL_MARKS: Record<MarkType, boolean> = {
  bass_drop: true, bass_start: true, bass_end: true, power_up: true,
  power_down: true, quiet: true, charging: true, tempo_change: true,
};

const LAYERS = [rmsBands, avgLines, diamonds, librosaOverlays, musicMarks, aiMarkers, playhead, beatStrips];

const BAND_CHIPS: { key: 'total' | 'bass' | 'mid' | 'high' | 'marks'; label: string; bg: string }[] = [
  { key: 'total', label: 'Total', bg: '#555' },
  { key: 'bass', label: 'Bass', bg: 'rgba(46,204,113,0.6)' },
  { key: 'mid', label: 'Mids', bg: 'rgba(230,126,34,0.6)' },
  { key: 'high', label: 'Highs', bg: 'rgba(52,152,219,0.6)' },
  { key: 'marks', label: 'Marks', bg: 'var(--surface2)' },
];

const LIBROSA_CHIPS: { key: keyof ViewState['librosaFilters']; label: string; bg: string }[] = [
  { key: 'sections', label: 'Sections', bg: 'rgba(68,136,255,0.5)' },
  { key: 'beats', label: 'Beats', bg: 'rgba(255,255,255,0.2)' },
  { key: 'onsets', label: 'Onsets', bg: 'rgba(255,136,0,0.5)' },
  { key: 'harmonic', label: 'Harmonic', bg: 'rgba(204,102,255,0.5)' },
  { key: 'bass', label: 'Bass', bg: 'rgba(68,221,136,0.5)' },
];

export default function ReviewPanel({
  uri,
  cached,
  durationMs,
  events,
  navLabel,
  onNav,
  mutateSet,
  onManualAdd,
  onQuickAdd,
  actions,
}: {
  uri: string;
  cached: CachedSet;
  durationMs: number;
  events: EventOption[];
  navLabel: string;
  onNav: (delta: number) => void;
  /** Immutable update of the cached set (page owns the cache). */
  mutateSet: (fn: (s: CachedSet) => CachedSet) => void;
  onManualAdd: (prefillMs: number | null) => void;
  /** right-click quick add with last-used event; returns false when no recent event */
  onQuickAdd: (ms: number) => void;
  actions: React.ReactNode;
}) {
  const qc = useQueryClient();
  const { data: settings } = useSettings();
  const { data: meta } = useAudioShapeMeta(uri);
  const { data: shape } = useAudioShapeData(uri, meta?.capture_complete ?? true);
  const { data: librosa } = useLibrosa(uri);
  const track = useLiveStore((s) => s.track);

  const [filters, setFilters] = useState({ total: true, bass: true, mid: true, high: true, marks: true });
  const [avgFilters, setAvgFilters] = useState({ total: false, bass: false, mid: false, high: false });
  const [librosaFilters, setLibrosaFilters] = useState({
    sections: true, beats: true, onsets: true, harmonic: true, bass: true, snare: false, mfcc: false,
  });
  const [canvasHeight, setCanvasHeight] = useState(140);
  const [highlightIdx, setHighlightIdx] = useState<number | null>(null);
  const [librosaBusy, setLibrosaBusy] = useState(false);

  // Playhead only when the review song is actually playing.
  const trackUriRef = useRef<string | null>(null);
  trackUriRef.current = track?.spotify_uri ?? null;
  const uriRef = useRef(uri);
  uriRef.current = uri;
  const latencyRef = useRef(0);
  latencyRef.current = Number(settings?.audio_latency_ms ?? 0);
  const getNowMs = useCallback(() => {
    if (trackUriRef.current !== uriRef.current) return null;
    const p = getLiveProgressMs();
    return p === null ? null : p - latencyRef.current;
  }, []);

  const followWin = useFollowWindow({
    getNowMs,
    durationMs,
    seedWindowS: settings ? Number(settings.builder_zoom_window_s ?? 20) : undefined,
    seedFutureS: settings ? Number(settings.builder_future_buffer_s ?? 5) : undefined,
    keyPrefix: 'ai.',
  });

  const averages = useMemo(
    () => (shape ? computeAverages(shape, Number(settings?.shape_average_window_ms ?? 500)) : null),
    [shape, settings],
  );
  const mfccDistances = useMemo(() => computeMfccDistances(librosa ?? null), [librosa]);
  const maxRms = useMemo(() => (shape ? Math.max(...shape.rms_total, 1e-9) : null), [shape]);

  const view: ViewState = useMemo(() => ({
    filters, avgFilters, markFilters: ALL_MARKS, librosaFilters,
    scales: { total: 1, bass: 1, mid: 1, high: 1 },
    scaleOverall: 1,
    offsetMs: Number(meta?.timestamp_offset_ms ?? 0),
    librosaOffsetMs: Number((librosa as { librosa_offset_ms?: number } | undefined)?.librosa_offset_ms ?? 0),
    triggerOffsetMs: 0,
    maxRms,
    intensityMode: 'off',
    advanced: false,
  }), [filters, avgFilters, librosaFilters, meta, librosa, maxRms]);

  const data: LayerDataBag = useMemo(() => ({
    shape: shape ?? null,
    averages,
    meta: meta ?? null,
    librosa: librosa ?? null,
    mfccDistances,
    triggers: [], events: [], calibrationTargetsMs: [],
    draggingIntensity: null, selectedIds: [], hoverTriggerId: null,
    aiMarkers: cached.suggestions.map((s, i) => ({
      ms: s.timestamp_ms,
      color: markerColor(s),
      eventColor: events.find((e) => e.id === s.event_id)?.color ?? null,
      highlighted: i === highlightIdx,
    })),
  }), [shape, averages, meta, librosa, mfccDistances, cached.suggestions, events, highlightIdx]);

  // ── Marker drag / click / dblclick / right-click ───────────────────────────
  const drag = useRef<{ idx: number; moved: boolean } | null>(null);
  const librosaRef = useRef(librosa ?? null);
  librosaRef.current = librosa ?? null;
  const librosaOffRef = useRef(0);
  librosaOffRef.current = view.librosaOffsetMs;

  const snap = (rawMs: number, y: number, g: FrameGeom) =>
    snapTimestamp(Math.round(rawMs / 20) * 20, y, {
      librosa: librosaRef.current,
      librosaOffsetMs: librosaOffRef.current,
      mainH: g.mainH,
      win: g.win,
      canvasW: g.w,
    });

  const rel = (ev: PointerEvent) => {
    const r = (ev.target as HTMLElement).getBoundingClientRect();
    return { x: ev.clientX - r.left, y: ev.clientY - r.top };
  };

  const highlight = (idx: number) => {
    setHighlightIdx(idx);
    document.getElementById(`sug-${idx}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  };

  const pointer = {
    onHit: (hit: Hit) => {
      if (hit?.kind === 'ai-marker') drag.current = { idx: hit.index, moved: false };
    },
    onDragMove: (ev: PointerEvent, g: FrameGeom) => {
      if (!drag.current) return;
      const { x, y } = rel(ev);
      drag.current.moved = true;
      const ms = snap(g.xToTime(x), y, g);
      const idx = drag.current.idx;
      mutateSet((s) => ({
        ...s,
        suggestions: s.suggestions.map((sg, i) => (i === idx ? { ...sg, timestamp_ms: ms } : sg)),
      }));
    },
    onDragEnd: () => {
      if (!drag.current) return;
      const { idx, moved } = drag.current;
      drag.current = null;
      if (!moved) {
        highlight(idx);
      } else {
        // Re-sort by timestamp after a move (highlight follows the row).
        mutateSet((s) => ({
          ...s,
          suggestions: [...s.suggestions].sort((a, b) => a.timestamp_ms - b.timestamp_ms),
        }));
        setHighlightIdx(null);
      }
    },
    onDoubleClick: (ms: number, y: number, hit: Hit, g: FrameGeom) => {
      if (hit?.kind === 'ai-marker') { highlight(hit.index); return; }
      onManualAdd(snap(ms, y, g));
    },
    onContextMenu: (ms: number, _hit: Hit, y?: number, g?: FrameGeom) => {
      onQuickAdd(g && y !== undefined ? snap(ms, y, g) : Math.round(ms / 20) * 20);
      return undefined;
    },
    onPan: (deltaMs: number) => {
      const w = followWin.getWin();
      followWin.setFollow(false);
      followWin.setManualWin({ startMs: w.startMs + deltaMs, endMs: w.endMs + deltaMs });
    },
  };

  const runLibrosa = async () => {
    setLibrosaBusy(true);
    try {
      const existing = await apiGet(`/audio-shape/librosa?uri=${encodeURIComponent(uri)}`).catch(() => null);
      if (existing) {
        qc.setQueryData(['librosa', uri], existing);
        return;
      }
      const res = await apiPost<{ status?: string }>('/audio-shape/librosa-analyze', { uri });
      if (res.status === 'no_wav') { alert('No WAV file found. Capture the song first.'); return; }
      if (res.status === 'no_meta') { alert('No audio shape found for this song.'); return; }
      // Poll until the background analysis lands (≤60s).
      for (let i = 0; i < 30; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const la = await apiGet(`/audio-shape/librosa?uri=${encodeURIComponent(uri)}`).catch(() => null);
        if (la) { qc.setQueryData(['librosa', uri], la); break; }
      }
    } catch (e) {
      alert(`Librosa analysis failed: ${e}`);
    } finally {
      setLibrosaBusy(false);
    }
  };

  const laSummary = librosa?.beats?.length
    ? `${librosa.tempo_bpm.toFixed(1)} BPM  •  ${librosa.beats.length} beats  •  ` +
      `${librosa.sections.length} sections  •  ${librosa.onsets.length} onsets  •  ` +
      `${(librosa.bass_onsets as unknown[] | undefined)?.length ?? 0} bass  •  ${librosa.harmonic_changes?.length ?? 0} harmonic`
    : '';

  return (
    <div className="card" style={{ marginTop: 12 }}>
      {/* Nav + filter chips */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
        <button style={{ fontSize: 12, padding: '4px 10px' }} onClick={() => onNav(-1)}>← Prev</button>
        <span style={{ fontSize: 12, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{navLabel}</span>
        <button style={{ fontSize: 12, padding: '4px 10px' }} onClick={() => onNav(1)}>Next →</button>
        <span style={{ fontSize: 13, fontWeight: 600, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {cached.artist} — {cached.title} ({cached.suggestions.length})
        </span>
        {!!cached.cost_usd && (
          <span style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}
            title={`Actual cost: $${cached.cost_usd.toFixed(6)} | ${cached.input_tokens} input tokens, ${cached.output_tokens} output tokens`}>
            ${cached.cost_usd.toFixed(4)}  ({cached.input_tokens}↑ {cached.output_tokens}↓ tok)
          </span>
        )}
        <button style={{ fontSize: 11, padding: '3px 9px' }} onClick={() => onManualAdd(getNowMs())}>+ Add Trigger</button>
        <div style={{ width: 1, height: 18, background: 'var(--border)', margin: '0 2px' }} />
        {BAND_CHIPS.map((c) => (
          <button key={c.key}
            title="Click: toggle band · right-click: toggle rolling-average line"
            style={{
              padding: '3px 8px', fontSize: 11, borderRadius: 10,
              background: filters[c.key] ? c.bg : 'var(--surface2)',
              color: filters[c.key] ? '#fff' : 'var(--text-muted)',
              outline: c.key !== 'marks' && avgFilters[c.key as 'total'] ? '1px solid #fff' : undefined,
            }}
            onClick={() => setFilters((f) => ({ ...f, [c.key]: !f[c.key] }))}
            onContextMenu={(e) => {
              e.preventDefault();
              if (c.key !== 'marks') setAvgFilters((f) => ({ ...f, [c.key]: !f[c.key as 'total'] }));
            }}>
            {c.label}
          </button>
        ))}
      </div>

      {/* Librosa filter row */}
      {!!librosa?.beats?.length && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Librosa:</span>
          {LIBROSA_CHIPS.map((c) => (
            <button key={c.key}
              style={{
                padding: '3px 8px', fontSize: 11, borderRadius: 10,
                background: librosaFilters[c.key] ? c.bg : 'var(--surface2)',
                color: librosaFilters[c.key] ? '#fff' : 'var(--text-muted)',
              }}
              onClick={() => setLibrosaFilters((f) => ({ ...f, [c.key]: !f[c.key] }))}>
              {c.label}
            </button>
          ))}
          <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 4 }}>{laSummary}</span>
        </div>
      )}

      {/* Canvas */}
      <TimelineCanvas
        layers={LAYERS}
        data={data}
        view={view}
        getWin={followWin.getWin}
        getNowMs={getNowMs}
        height={canvasHeight}
        pointer={pointer}
      />
      <div
        title="Drag to resize"
        style={{ height: 8, cursor: 'ns-resize', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 8, userSelect: 'none' }}
        onPointerDown={(ev) => {
          ev.preventDefault();
          (ev.target as HTMLElement).setPointerCapture(ev.pointerId);
          const startY = ev.clientY;
          const startH = canvasHeight;
          const move = (e: PointerEvent) => setCanvasHeight(Math.max(80, Math.min(500, startH + (e.clientY - startY))));
          const up = () => {
            window.removeEventListener('pointermove', move);
            window.removeEventListener('pointerup', up);
          };
          window.addEventListener('pointermove', move);
          window.addEventListener('pointerup', up);
        }}
      >
        ⣀⣀⣀
      </div>

      {/* Zoom bar */}
      <div style={{ marginTop: 8 }}>
        <TimelineBar
          durationMs={durationMs}
          triggers={[]}
          events={[]}
          getWin={followWin.getWin}
          getNowMs={getNowMs}
          follow={followWin.follow}
          onManualWin={(w) => { followWin.setFollow(false); followWin.setManualWin(w); }}
          onAdjustFollow={(edge, deltaMs) => {
            if (edge === 'end' || edge === 'center') followWin.setFutureS((s) => Math.max(0, s + deltaMs / 1000));
            if (edge === 'start') followWin.setWindowS((s) => Math.max(2, s - deltaMs / 1000));
          }}
          onEdit={() => {}} onMove={() => {}} onDelete={() => {}} onCreate={() => {}} onArmedContext={() => {}}
        />
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 }}>
        <button style={{ fontSize: 12 }} onClick={followWin.fullSong}>Full Song</button>
        <button className={followWin.follow ? 'primary' : ''} style={{ fontSize: 12 }}
          onClick={() => followWin.setFollowSnapped(!followWin.follow)}>
          {followWin.follow ? 'Follow' : 'Manual'}
        </button>
        <button style={{ fontSize: 12 }} disabled={librosaBusy} title="Load librosa analysis overlay"
          onClick={() => void runLibrosa()}>
          {librosaBusy ? '…' : 'Librosa'}
        </button>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {!shape && meta !== undefined ? 'No audio shape available.' : ''}
        </span>
      </div>

      {/* Song feedback */}
      <div style={{ margin: '12px 0 8px' }}>
        <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
          Song feedback (sent to Analyze Learning)
        </label>
        <textarea rows={2}
          placeholder="e.g. All bass drops were right, intro trigger fired too early…"
          value={cached.songComment}
          style={{ width: '100%', fontSize: 12, resize: 'vertical' }}
          onChange={(e) => mutateSet((s) => ({ ...s, songComment: e.target.value }))} />
      </div>

      {actions}

      {/* Suggestion list */}
      <div style={{ overflowY: 'auto', maxHeight: '45vh', minHeight: 80, paddingRight: 4 }}>
        {cached.suggestions.map((sug, idx) => (
          <SuggestionRow
            key={idx}
            idx={idx}
            sug={sug}
            events={events}
            highlighted={idx === highlightIdx}
            onHighlight={() => setHighlightIdx(idx)}
            onChange={(next: Suggestion, resort?: boolean) => mutateSet((s) => {
              let sugs = s.suggestions.map((x, i) => (i === idx ? next : x));
              if (resort) sugs = [...sugs].sort((a, b) => a.timestamp_ms - b.timestamp_ms);
              return { ...s, suggestions: sugs };
            })}
          />
        ))}
      </div>
    </div>
  );
}
