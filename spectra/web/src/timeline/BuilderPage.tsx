import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import CollapsibleCard from '../components/CollapsibleCard';
import HelpLink from '../help/HelpLink';
import { useSticky } from '../lib/useSticky';
import { fmtMs } from '../lib/time';
import { useEvents, useSettings } from '../api/queries';
import { useBuilderStore } from './store';
import { useAudioShapeData, useAudioShapeMeta, useCalibrationStatus, useLibrosa, useLiveShape, useProfileByUri, useSetlists } from './queries';
import { usePlayhead } from './hooks/usePlayhead';
import { useFollowWindow } from './hooks/useFollowWindow';
import TimelineCanvas from './canvas/TimelineCanvas';
import { BUILDER_LAYERS } from './canvas/layers';
import { BEAT_STRIP_H, stripCountFor, type IntensityBgMode, type LayerDataBag, type ViewState } from './canvas/frame';
import { computeAverages, computeMfccDistances } from './canvas/data';
import ModeBar from './components/ModeBar';
import TimelineBar from './components/TimelineBar';
import ShapeControls from './components/ShapeControls';
import TriggerDialog from './components/TriggerDialog';
import TriggerList from './components/TriggerList';
import SpectraTriggersCard from './components/SpectraTriggersCard';
import PaletteCard from './components/PaletteCard';
import OffsetBadge from './components/OffsetBadge';
import ShiftAllControl from './components/ShiftAllControl';
import ImportDialog from './components/ImportDialog';
import { useBuilderWs } from './hooks/useBuilderWs';
import { useTriggerInteractions } from './hooks/useTriggerInteractions';
import { useIntensityKeyboard } from './hooks/useIntensityKeyboard';
import { usePaletteKeyboard } from './hooks/usePaletteKeyboard';
import { usePalettes } from './queries';
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
  // Legacy-builder port: surface whether auto-calibration is targeting this
  // song (only meaningful while its offset is still unverified).
  const { data: calStatus } = useCalibrationStatus(
    uri, (meta?.capture_complete ?? false) && meta?.offset_verification === 'unverified');
  const calibrating = !!calStatus?.active;
  const { data: storedShape } = useAudioShapeData(uri, meta?.capture_complete ?? false);
  const { data: librosa } = useLibrosa(uri);
  const { data: events } = useEvents();
  const { data: setlists } = useSetlists();

  // While capturing (analysis on, no completed shape yet) poll the live buffer.
  const analysisOn = useBuilderStore((s) => s.modes.analysis);
  const capturing = analysisOn && !!uri && !(meta?.capture_complete ?? false);
  const { data: liveShape } = useLiveShape(uri, capturing);
  const shape = storedShape ?? (capturing ? liveShape : undefined);

  useBuilderWs(uri);

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
  const [intensityMode, setIntensityMode] = useSticky<IntensityBgMode>('intensityMode', 'off');
  const [canvasHeight, setCanvasHeight] = useSticky('canvasHeight', 260);

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

  // Armed palette event (arming UI lands in Phase 3; right-click placement
  // is already wired through the store fields).
  const { data: palettes } = usePalettes();
  const palettesRef = useRef(palettes);
  palettesRef.current = palettes;
  const getArmedEventId = useCallback(() => {
    const st = useBuilderStore.getState();
    if (!st.armedKey || !st.activePaletteId) return null;
    return palettesRef.current?.find((pl) => pl.id === st.activePaletteId)?.keys[st.armedKey] ?? null;
  }, []);

  usePaletteKeyboard({
    getPalettes: () => palettesRef.current,
    onToggleFollow: () => followWin.setFollowSnapped(!followWin.follow),
  });
  useIntensityKeyboard({ onFollow: () => followWin.setFollowSnapped(true) });

  // In live mode, follow resumes (zoomed) on page open, on entering live
  // mode, and whenever the live song changes — a past pan or Full Song view
  // shouldn't leave the editor zoomed out. Within one song the user's choice
  // rules. Search mode has no playhead, so the manual view sticks there.
  useEffect(() => {
    if (!liveMode || !track?.uri) return;
    followWin.setFollowSnapped(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveMode, track?.uri]);

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
    intensityMode,
    advanced: false,
  }), [bandFilters, avgFilters, markFilters, librosaFilters, scales, meta, librosa,
       triggerPreviewOffsetMs, maxRms, intensityMode]);

  const canUndo = useBuilderStore((s) => s.undoStack.length > 0);
  const canRedo = useBuilderStore((s) => s.redoStack.length > 0);
  const blendBrush = useBuilderStore((s) => s.blendBrush);
  const [beatTip, setBeatTip] = useState<{ ms: number; values: Record<string, number> } | null>(null);
  const [shiftOpen, setShiftOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [hoverTriggerId, setHoverTriggerId] = useState<string | null>(null);
  const selectedIds = useBuilderStore((s) => s.selectedIds);
  const librosaRef = useRef(librosa ?? null);
  librosaRef.current = librosa ?? null;
  const librosaOffRef = useRef(0);
  librosaOffRef.current = view.librosaOffsetMs;
  const { pointer: triggerPointer, draggingIntensity } = useTriggerInteractions({
    getLibrosa: () => librosaRef.current,
    getLibrosaOffsetMs: () => librosaOffRef.current,
    getArmedEventId,
    onBeatTip: setBeatTip,
    onHover: setHoverTriggerId,
  });

  const data: LayerDataBag = useMemo(() => ({
    shape: shape ?? null,
    averages,
    meta: meta ?? null,
    librosa: librosa ?? null,
    mfccDistances,
    triggers: workingTriggers,
    events: (events ?? []).map((e) => ({ id: e.id, name: e.name, color: e.color, event_type: e.event_type })),
    calibrationTargetsMs,
    draggingIntensity,
    selectedIds,
    hoverTriggerId,
  }), [shape, averages, meta, librosa, mfccDistances, workingTriggers, events,
       calibrationTargetsMs, draggingIntensity, selectedIds, hoverTriggerId]);

  const stripCount = stripCountFor(data, librosaFilters);
  const totalCanvasHeight = canvasHeight + stripCount * BEAT_STRIP_H;

  return (
    <>
      <div className="card">
        <ModeBar />
      </div>

      <CollapsibleCard
        id="timeline"
        title={<>Timeline <HelpLink topic="builder-timeline-bar" title="Full-song timeline bar" /></>}
        headerExtra={
          <span style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 12 }}>
            {blendBrush && (
              <span
                title="Override Blend brush armed — right-click triggers to apply; Esc or re-press to disarm"
                style={{
                  padding: '1px 8px', borderRadius: 10, fontSize: 11,
                  background: blendBrush === 'set' ? 'rgba(168,85,247,0.25)' : 'rgba(231,76,60,0.25)',
                  border: '1px solid var(--border)', color: 'var(--text)',
                }}
              >
                ⤳ {blendBrush === 'set' ? 'paint blend [' : 'clear blend ]'}
              </span>
            )}
            <button disabled={!canUndo} title="Undo (Ctrl+Z)"
              onClick={() => useBuilderStore.getState().undo()}>
              ↶
            </button>
            <button disabled={!canRedo} title="Redo (Ctrl+Y)"
              onClick={() => useBuilderStore.getState().redo()}>
              ↷
            </button>
            <button onClick={() => followWin.setFollowSnapped(!followWin.follow)}
              className={followWin.follow ? 'primary' : ''}
              title="Toggle follow/manual zoom (` key) — enabling snaps to the playhead, disabling freezes the current view">
              {followWin.follow ? 'Follow' : 'Manual'}
            </button>
            <button onClick={followWin.fullSong}>Full Song</button>
            <span style={{ color: 'var(--text-muted)' }}>
              {fmtMs(coarseMs)} / {fmtMs(durationMs)}
            </span>
            <HelpLink topic="builder-pan-zoom" title="Pan, zoom & follow" />
            <HelpLink topic="builder" title="Builder help — shortcuts & gestures" />
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
          onEdit={(id) => useBuilderStore.getState().setEditingTrigger(id)}
          onMove={(id, ms) => useBuilderStore.getState().mutateWorking((ts) => {
            const t = ts.find((tt) => tt.id === id);
            if (t) t.timestamp_ms = ms;
          })}
          onDelete={(id) => useBuilderStore.getState().mutateWorking((ts) => {
            const i = ts.findIndex((tt) => tt.id === id);
            if (i >= 0) ts.splice(i, 1);
          })}
          onCreate={(ms) => useBuilderStore.getState().setEditingTrigger(`new:${ms}`)}
          onArmedContext={(ms, tid) => triggerPointer.onContextMenu?.(ms,
            tid ? { kind: 'trigger-triangle', triggerId: tid } : null)}
        />
      </CollapsibleCard>

      <SpectraTriggersCard
        uri={uri}
        durationMs={durationMs}
        getWin={followWin.getWin}
        getNowMs={getNowMs}
      />

      <CollapsibleCard
        id="shape"
        title={<>Audio Shape <HelpLink topic="builder-mouse" title="Canvas mouse actions" />
          <HelpLink topic="builder-selection-keys" title="Selection & intensity keys" /></>}
        headerExtra={
          <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            {capturing && (
              <span style={{ fontSize: 11, color: 'var(--accent2)' }}>● capturing…</span>
            )}
            {calibrating && (
              <span style={{ fontSize: 11, color: 'var(--accent2)' }}
                title="xcorr auto-calibration is currently targeting this song's offset">
                🎯 auto-calibrating…
              </span>
            )}
            <OffsetBadge meta={meta ?? null} uri={uri} />
            <HelpLink topic="builder-misc" title="Other timeline controls" />
            <button
              style={{ fontSize: 12 }}
              className={shiftOpen || triggerPreviewOffsetMs !== 0 ? 'primary' : ''}
              disabled={!profile}
              title="Shift every trigger by a fixed offset (preview + commit)"
              onClick={() => setShiftOpen((v) => !v)}
            >
              ⇄
            </button>
            <button
              style={{ fontSize: 12 }}
              disabled={!profile}
              title="Add a trigger at the current playhead"
              onClick={() => {
                const now = getNowMs() ?? 0;
                useBuilderStore.getState().setEditingTrigger(`new:${Math.round(now / 20) * 20}`);
              }}
            >
              + Add Trigger
            </button>
          </span>
        }
      >
        <TimelineCanvas
          layers={BUILDER_LAYERS}
          data={data}
          view={view}
          getWin={followWin.getWin}
          getNowMs={getCanvasNowMs}
          height={totalCanvasHeight}
          pointer={{
            ...triggerPointer,
            onPan: (deltaMs) => {
              const w = followWin.getWin();
              followWin.setFollow(false);
              followWin.setManualWin({ startMs: w.startMs + deltaMs, endMs: w.endMs + deltaMs });
            },
          }}
        />
        <div
          title="Drag to resize the canvas"
          style={{ height: 8, cursor: 'ns-resize', display: 'flex', alignItems: 'center',
                   justifyContent: 'center', color: 'var(--text-muted)', fontSize: 8, userSelect: 'none' }}
          onPointerDown={(ev) => {
            ev.preventDefault();
            (ev.target as HTMLElement).setPointerCapture(ev.pointerId);
            const startY = ev.clientY;
            const startH = canvasHeight;
            const move = (e: PointerEvent) =>
              setCanvasHeight(Math.max(120, Math.min(700, startH + (e.clientY - startY))));
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
        <ShiftAllControl open={shiftOpen} setOpen={setShiftOpen} durationMs={durationMs} />
        <HelpLink topic="builder-navigation" title="Navigation & view" />
        {beatTip && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
            beat @ {fmtMs(beatTip.ms)} —{' '}
            {Object.entries(beatTip.values).map(([k, v]) => `${k} ${v.toFixed(2)}`).join(' · ')}
            <button style={{ marginLeft: 8, fontSize: 10, padding: '1px 6px' }}
              onClick={() => setBeatTip(null)}>✕</button>
          </div>
        )}
        <HelpLink topic="builder-shape-controls" title="Waveform & layer controls" />
        <ShapeControls
          view={view}
          setFilters={(p) => setBandFilters((f) => ({ ...f, ...p }))}
          setAvgFilters={(p) => setAvgFilters((f) => ({ ...f, ...p }))}
          setScales={(band, v) => setScalesRaw((s) => ({ ...s, [band]: v }))}
          setLibrosaFilter={(k, v) => setLibrosaFilters((f) => ({ ...f, [k]: v }))}
          setIntensityMode={setIntensityMode}
          hasLibrosa={!!librosa?.beats?.length}
          hasIntensityCurve={!!shape?.avg_rms_1s?.length}
        />
      </CollapsibleCard>

      <CollapsibleCard id="palettes"
        title={<>Palettes <HelpLink topic="builder-palette-keys" title="Keyboard palettes" />
          <HelpLink topic="builder-palette-card" title="Palette card gestures" /></>}
        defaultCollapsed>
        <PaletteCard events={data.events} />
      </CollapsibleCard>

      <CollapsibleCard id="triggers" title="All Triggers">
        <TriggerList triggers={workingTriggers} events={data.events} onImport={() => setImportOpen(true)} />
      </CollapsibleCard>

      <TriggerDialog events={data.events} />
      {importOpen && (
        <ImportDialog uri={uri} setlists={setlists ?? []} onClose={() => setImportOpen(false)} />
      )}

      {!uri && (
        <p className="empty-note">
          {liveMode ? 'Play something on Spotify, or switch off Live and search a song.' : 'Search a song above.'}
        </p>
      )}
    </>
  );
}
