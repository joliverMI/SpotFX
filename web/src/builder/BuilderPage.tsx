import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import CollapsibleCard from '../components/CollapsibleCard';
import { useSticky } from '../lib/useSticky';
import { fmtMs } from '../lib/time';
import { useEvents, useSettings } from '../api/queries';
import { useBuilderStore } from './store';
import { useAudioShapeData, useAudioShapeMeta, useLibrosa, useProfileByUri } from './queries';
import { usePlayhead } from './hooks/usePlayhead';
import { useFollowWindow } from './hooks/useFollowWindow';
import TimelineCanvas from './canvas/TimelineCanvas';
import { BUILDER_LAYERS } from './canvas/layers';
import { BEAT_STRIP_H, stripCountFor, type Hit, type LayerDataBag, type ViewState } from './canvas/frame';
import { computeAverages, computeMfccDistances } from './canvas/data';
import ModeBar from './components/ModeBar';
import TimelineBar from './components/TimelineBar';
import ShapeControls from './components/ShapeControls';
import type { MarkType } from './types';

const ALL_MARKS: Record<MarkType, boolean> = {
  bass_drop: true, bass_start: true, bass_end: true, power_up: true,
  power_down: true, quiet: true, charging: true, tempo_change: true,
};

export default function BuilderPage() {
  const { getNowMs, coarseMs } = usePlayhead();
  const track = useBuilderStore((s) => s.track);
  const manualUri = useBuilderStore((s) => s.manualUri);
  const liveMode = useBuilderStore((s) => s.liveMode);
  const autoWait = useBuilderStore((s) => s.autoWait);
  const profile = useBuilderStore((s) => s.profile);
  const dirty = useBuilderStore((s) => s.dirty);
  const slotId = useBuilderStore((s) => s.slotId);
  const loadProfile = useBuilderStore((s) => s.loadProfile);
  const calibrationTargetsMs = useBuilderStore((s) => s.calibrationTargetsMs);
  const triggerPreviewOffsetMs = useBuilderStore((s) => s.triggerPreviewOffsetMs);

  // Auto-wait locks the shown song until playback moves on being disabled.
  const lockedUri = useRef<string | null>(null);
  const liveUri = track?.uri ?? null;
  if (autoWait && lockedUri.current === null && liveUri) lockedUri.current = liveUri;
  if (!autoWait) lockedUri.current = null;
  const uri = liveMode ? (autoWait ? lockedUri.current ?? liveUri : liveUri) : manualUri;

  const { data: settings } = useSettings();
  const { data: profileData } = useProfileByUri(uri);
  const { data: meta } = useAudioShapeMeta(uri);
  const { data: shape } = useAudioShapeData(uri, meta?.capture_complete ?? false);
  const { data: librosa } = useLibrosa(uri);
  const { data: events } = useEvents();

  // Load fetched profile into the editable store (never clobber unsaved edits).
  useEffect(() => {
    if (!profileData) return;
    const cur = useBuilderStore.getState().profile;
    if (cur?.spotify_uri === profileData.spotify_uri && dirty) return;
    loadProfile(profileData);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profileData]);

  // ── sticky view state ────────────────────────────────────────────────────
  const [bandFilters, setBandFilters] = useSticky('bandFilters',
    { total: true, bass: true, mid: true, high: true, marks: true });
  const [avgFilters, setAvgFilters] = useSticky('avgFilters',
    { total: false, bass: false, mid: false, high: false });
  const [scales, setScalesRaw] = useSticky('scales',
    { total: 1, bass: 1, mid: 1, high: 1 },
    settings ? {
      total: Number(settings.shape_scale_total ?? 1), bass: Number(settings.shape_scale_bass ?? 1),
      mid: Number(settings.shape_scale_mid ?? 1), high: Number(settings.shape_scale_high ?? 1),
    } : undefined);
  const [librosaFilters, setLibrosaFilters] = useSticky('librosaFilters',
    { sections: true, beats: true, onsets: false, harmonic: false, bass: false, snare: false, mfcc: false });
  const [markFilters] = useSticky<Record<MarkType, boolean>>('markFilters', ALL_MARKS);
  const [intensityBg, setIntensityBg] = useSticky('intensityBg', false);
  const [canvasHeight] = useSticky('canvasHeight', 260);

  const durationMs = profile?.duration_ms || meta?.duration_ms || track?.duration_ms || 1;

  // Canvas playhead shows the AUDIBLE moment: raw progress minus the audio
  // chain latency (legacy: setPlayhead(p - audio_latency_ms)). The timeline
  // bar and follow window intentionally use raw progress, matching legacy.
  const audioLatencyRef = useRef(0);
  audioLatencyRef.current = Number(settings?.audio_latency_ms ?? 0);
  const getCanvasNowMs = useCallback(() => {
    const now = getNowMs();
    return now === null ? null : now - audioLatencyRef.current;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const followWin = useFollowWindow({
    getNowMs,
    durationMs,
    seedWindowS: settings ? Number(settings.builder_zoom_window_s ?? 30) : undefined,
    seedFutureS: settings ? Number(settings.builder_future_buffer_s ?? 10) : undefined,
  });

  const workingTriggers = useMemo(() => {
    if (!profile) return [];
    return slotId ? profile.setlist_triggers[slotId] ?? profile.triggers : profile.triggers;
  }, [profile, slotId]);

  const averages = useMemo(
    () => (shape ? computeAverages(shape, Number(settings?.shape_average_window_ms ?? 4000)) : null),
    [shape, settings],
  );
  const mfccDistances = useMemo(() => computeMfccDistances(librosa ?? null), [librosa]);
  const maxRms = useMemo(() => (shape ? Math.max(...shape.rms_total, 1e-9) : null), [shape]);

  const view: ViewState = useMemo(() => ({
    filters: bandFilters,
    avgFilters,
    markFilters,
    librosaFilters,
    scales,
    scaleOverall: 1,
    offsetMs: Number(meta?.timestamp_offset_ms ?? 0),
    librosaOffsetMs: Number((librosa as { librosa_offset_ms?: number } | undefined)?.librosa_offset_ms ?? 0),
    triggerOffsetMs: triggerPreviewOffsetMs,
    maxRms,
    intensityBg,
    advanced: false,
  }), [bandFilters, avgFilters, markFilters, librosaFilters, scales, meta, librosa,
       triggerPreviewOffsetMs, maxRms, intensityBg]);

  const data: LayerDataBag = useMemo(() => ({
    shape: shape ?? null,
    averages,
    meta: meta ?? null,
    librosa: librosa ?? null,
    mfccDistances,
    triggers: workingTriggers,
    events: (events ?? []).map((e) => ({ id: e.id, name: e.name, color: e.color })),
    calibrationTargetsMs,
    draggingIntensity: null,
  }), [shape, averages, meta, librosa, mfccDistances, workingTriggers, events, calibrationTargetsMs]);

  const stripCount = stripCountFor(data, librosaFilters);
  const totalCanvasHeight = canvasHeight + stripCount * BEAT_STRIP_H;

  const [beatTip, setBeatTip] = useState<{ ms: number; values: Record<string, number> } | null>(null);

  return (
    <>
      <div className="card">
        <ModeBar />
      </div>

      <CollapsibleCard
        id="timeline"
        title="Timeline"
        headerExtra={
          <span style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 12 }}>
            <button onClick={() => followWin.setFollow(!followWin.follow)}
              className={followWin.follow ? 'primary' : ''}
              title="Toggle follow/manual zoom (` key)">
              {followWin.follow ? 'Follow' : 'Manual'}
            </button>
            <button onClick={followWin.fullSong}>Full Song</button>
            <span style={{ color: 'var(--text-muted)' }}>
              {fmtMs(coarseMs)} / {fmtMs(durationMs)}
            </span>
          </span>
        }
      >
        <TimelineBar
          durationMs={durationMs}
          triggers={workingTriggers}
          events={data.events}
          getWin={followWin.getWin}
          getNowMs={getNowMs}
          follow={followWin.follow}
          onManualWin={(w) => { followWin.setFollow(false); followWin.setManualWin(w); }}
          onAdjustFollow={(edge, deltaMs) => {
            if (edge === 'end' || edge === 'center') followWin.setFutureS((s) => Math.max(0, s + deltaMs / 1000));
            if (edge === 'start') followWin.setWindowS((s) => Math.max(2, s - deltaMs / 1000));
          }}
        />
      </CollapsibleCard>

      <CollapsibleCard id="shape" title="Audio Shape">
        <TimelineCanvas
          layers={BUILDER_LAYERS}
          data={data}
          view={view}
          getWin={followWin.getWin}
          getNowMs={getCanvasNowMs}
          height={totalCanvasHeight}
          pointer={{
            onHit: (hit: Hit) => {
              if (hit?.kind === 'beat') setBeatTip({ ms: hit.beatMs, values: hit.values });
              else setBeatTip(null);
            },
            onPan: (deltaMs) => {
              const w = followWin.getWin();
              followWin.setFollow(false);
              followWin.setManualWin({ startMs: w.startMs + deltaMs, endMs: w.endMs + deltaMs });
            },
          }}
        />
        {beatTip && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
            beat @ {fmtMs(beatTip.ms)} —{' '}
            {Object.entries(beatTip.values).map(([k, v]) => `${k} ${v.toFixed(2)}`).join(' · ')}
            <button style={{ marginLeft: 8, fontSize: 10, padding: '1px 6px' }}
              onClick={() => setBeatTip(null)}>✕</button>
          </div>
        )}
        <ShapeControls
          view={view}
          setFilters={(p) => setBandFilters((f) => ({ ...f, ...p }))}
          setAvgFilters={(p) => setAvgFilters((f) => ({ ...f, ...p }))}
          setScales={(band, v) => setScalesRaw((s) => ({ ...s, [band]: v }))}
          setLibrosaFilter={(k, v) => setLibrosaFilters((f) => ({ ...f, [k]: v }))}
          setIntensityBg={setIntensityBg}
          hasLibrosa={!!librosa?.beats?.length}
          hasIntensityCurve={!!shape?.avg_rms_1s?.length}
        />
      </CollapsibleCard>

      {!uri && (
        <p className="empty-note">
          {liveMode ? 'Play something on Spotify, or switch off Live and search a song.' : 'Search a song above.'}
        </p>
      )}
    </>
  );
}
