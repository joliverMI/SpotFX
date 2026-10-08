import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import CollapsibleCard from '../components/CollapsibleCard';
import HelpLink from '../help/HelpLink';
import SonicChatPopover from '../components/SonicChatPopover';
import ShowCueBar from './components/ShowCueBar';
import { useSticky } from '../lib/useSticky';
import { fmtMs } from '../lib/time';
import { useEvents, useSettings } from '../api/queries';
import { useBuilderStore } from './store';
import { useAnalysedPlan, useAudioShapeData, useAudioShapeMeta, useCalibrationStatus, useDropRails, useDropSequences, useLibrosa, useLiveShape, useProfileByUri, useSetlists, useShowArms } from './queries';
import { FLARE_MARKER_COLOR, SCENE_MARKER_COLOR, songPositionMarkers } from '../debug/plannedEvents';
import { LIGHT_SHOW_COLOR, lightShowCueMarkers, sceneChangeArms } from './lightShowMarkers';
import AnalysedEventsStrip from './components/AnalysedEventsStrip';
import { usePlayhead } from './hooks/usePlayhead';
import { useFollowWindow } from './hooks/useFollowWindow';
import { drawnPlayheadMs } from './hooks/followWindow';
import TimelineCanvas from './canvas/TimelineCanvas';
import { BUILDER_LAYERS } from './canvas/layers';
import { BEAT_STRIP_H, snapRailHFor, stripCountFor, type IntensityBgMode, type LayerDataBag, type ViewState } from './canvas/frame';
import { DEFAULT_BEAT_MS, PHASE_COLOR, buildDisplay, zoomWindow, type Handle } from './dropSequences';
import DropSequenceStrip from './components/DropSequenceStrip';
import DropSequencesCard from './components/DropSequencesCard';
import DropSeqToolbar from './components/DropSeqToolbar';
import { useDropEditor } from './hooks/useDropEditor';
import { DROP_FOCUS_ATTR, useDropSeqInteractions } from './hooks/useDropSeqInteractions';
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
import { useLightShowDrag } from './hooks/useLightShowDrag';
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
  const { data: analysedPlan, refetch: refetchAnalysedPlan } = useAnalysedPlan(uri);

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
  const [showAnalysedEvents, setShowAnalysedEvents] = useSticky('showAnalysedEvents', true);
  const [showDropSeqs, setShowDropSeqs] = useSticky('showDropSequences', true);
  const [showDismissedDrops, setShowDismissedDrops] = useSticky('dropShowDismissed', false);
  const [showLightShow, setShowLightShow] = useSticky('showLightShowMarkers', true);

  const durationMs = profile?.duration_ms || meta?.duration_ms || track?.duration_ms || 1;

  // Canvas playhead shows the AUDIBLE moment: raw progress minus the audio
  // chain latency (legacy: setPlayhead(p - audio_latency_ms)). The timeline
  // bar uses raw progress, matching legacy. The playhead LAYER draws that
  // audible moment shifted by the song's shape offset (view.offsetMs), so the
  // FOLLOW WINDOW anchors on exactly that drawn position — never the raw
  // clock, which on a song with a large stored offset (Pop Off: 14,450 ms)
  // left the playhead drawn past the window's right edge for the whole
  // song. See hooks/followWindow.ts.
  const audioLatencyRef = useRef(0);
  audioLatencyRef.current = Number(settings?.audio_latency_ms ?? 0);
  const shapeOffsetRef = useRef(0);
  shapeOffsetRef.current = Number(meta?.timestamp_offset_ms ?? 0);
  const getCanvasNowMs = useCallback(() => {
    const now = getNowMs();
    return now === null ? null : now - audioLatencyRef.current;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const getPlayheadMs = useCallback(() => {
    const now = getCanvasNowMs();
    return now === null ? null : drawnPlayheadMs(now, shapeOffsetRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const followWin = useFollowWindow({
    getNowMs: getPlayheadMs,
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

  // The drop-sequence keyboard (C L D · ← → · Enter · Delete · N P ·
  // Ctrl+Z) goes FIRST while a sequence has the Timeline's attention: this
  // capture listener is registered before the palette and intensity keys,
  // and stops a key it uses from reaching them. The handler is filled in
  // below, once the sequences are known (./hooks/useDropSeqInteractions.ts).
  const dropKeyRef = useRef<((e: KeyboardEvent) => boolean) | null>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (dropKeyRef.current?.(e)) {
        e.preventDefault();
        e.stopImmediatePropagation();
      }
    };
    window.addEventListener('keydown', onKey, { capture: true });
    return () => window.removeEventListener('keydown', onKey, { capture: true });
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

  // Analysed events (scene changes + analysed flares) at their SONG position —
  // see ../debug/plannedEvents.ts's module docstring for why the Timeline
  // canvas needs a different placement than the debug page's own clock-shifted one.
  // The SAME list also draws on the full-song strip (AnalysedEventsStrip,
  // below) — one source of truth for what will fire, never a second one.
  const analysedMarkers = useMemo(
    () => (showAnalysedEvents ? songPositionMarkers(analysedPlan) : []),
    [showAnalysedEvents, analysedPlan]);

  // The Light Show's High/Low Trigger markers — his ask: "see a marker
  // showing where the light show triggers are, even if they aren't
  // active" (./lightShowMarkers.ts). `showArms` is global room state
  // (spectra/services/show_arms.py), polled independently of which song
  // is shown; a scene_change-armed set has no fixed song position, so it
  // is named in the legend below rather than drawn as a marker.
  const { data: showArms } = useShowArms(!!uri);
  const lightShowCues = useMemo(
    () => (showLightShow ? lightShowCueMarkers(analysedPlan?.show_cues, showArms, uri) : []),
    [showLightShow, analysedPlan, showArms, uri]);
  const armedSceneChangeSets = useMemo(() => sceneChangeArms(showArms, uri), [showArms, uri]);
  const lightShowUi = useLightShowDrag({
    uri, durationMs,
    getBeats: () => librosaRef.current?.beats ?? null,
    onChanged: () => void refetchAnalysedPlan(),
  });

  // ── drop sequences (drop-detection plan, phases 3–4) ────────────────────
  // ./dropSequences.ts decides what each sequence IS (its look, whether it
  // fires, its words); the canvas layer, the strip and the review card all
  // draw that one list. Editing (phase 4): ./hooks/useDropEditor.ts saves,
  // ./hooks/useDropSeqInteractions.ts turns a hand on the graph into edits.
  const { data: dropResp, isLoading: dropLoading, error: dropError } = useDropSequences(uri);
  const { data: dropRails } = useDropRails(uri, showDropSeqs);
  const [dropSel, setDropSel] = useState<string | null>(null);
  const [dropHover, setDropHover] = useState<{ key: string; handle: Handle } | null>(null);
  useEffect(() => { setDropSel(null); setDropHover(null); }, [uri]);
  const analysedApplies = analysedPlan ? analysedPlan.applies : true;
  const dropSeqs = useMemo(
    () => buildDisplay(dropResp, { showDismissed: showDismissedDrops, analysedApplies }),
    [dropResp, showDismissedDrops, analysedApplies]);
  const dropBeatMs = dropResp?.song?.beat_ms ?? dropRails?.beat_ms ?? DEFAULT_BEAT_MS;
  const dropCapturedFrom = dropResp?.song?.captured_from_ms ?? dropRails?.captured_from_ms ?? null;
  const dropRailsOk = dropRails?.status === 'ok' ? dropRails : null;
  const canvasWrapRef = useRef<HTMLDivElement>(null);
  const detailRef = useRef<HTMLDivElement>(null);
  const showDropDetail = useCallback(
    () => detailRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }), []);
  const dropEditor = useDropEditor(uri);
  // jumpToDrop is defined below; the interactions reach it through a ref
  const jumpRef = useRef<(key: string) => void>(() => {});
  const dropUi = useDropSeqInteractions({
    seqs: dropSeqs, rails: dropRailsOk, beatMs: dropBeatMs, editor: dropEditor,
    selectedKey: dropSel, setSelectedKey: setDropSel,
    onJump: (key) => jumpRef.current(key), onShowDetail: showDropDetail,
  });
  dropKeyRef.current = showDropSeqs ? dropUi.onKey : null;
  const dropLayer = useMemo(() => {
    if (!showDropSeqs || (!dropSeqs.length && !dropRailsOk && !dropUi.adding)) return null;
    return { seqs: dropSeqs, rails: dropRailsOk, selectedKey: dropSel, hover: dropHover,
             selectedHandle: dropUi.selHandle, adding: dropUi.adding, live: dropUi.live,
             capturedFromMs: dropCapturedFrom, beatMs: dropBeatMs };
  }, [showDropSeqs, dropSeqs, dropRailsOk, dropSel, dropHover, dropUi.selHandle, dropUi.adding,
      dropUi.live, dropCapturedFrom, dropBeatMs]);
  const jumpToDrop = useCallback((key: string) => {
    const seq = dropSeqs.find((q) => q.key === key);
    if (!seq) return;
    followWin.setFollow(false);
    followWin.setManualWin(zoomWindow(seq, dropBeatMs, durationMs));
    canvasWrapRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dropSeqs, dropBeatMs, durationMs]);
  jumpRef.current = jumpToDrop;
  const selectedDrop = dropSeqs.find((q) => q.key === dropSel) ?? null;

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
    plannedEvents: analysedMarkers,
    dropSeq: dropLayer,
    lightShow: lightShowCues,
    lightShowDrag: lightShowUi.liveMs,
  }), [shape, averages, meta, librosa, mfccDistances, workingTriggers, events,
       calibrationTargetsMs, draggingIntensity, selectedIds, hoverTriggerId, analysedMarkers, dropLayer,
       lightShowCues, lightShowUi.liveMs]);

  const stripCount = stripCountFor(data, librosaFilters);
  // The drop-sequence snap rails get their own band under the main area, so
  // the waveform keeps its height when the layer is on.
  const totalCanvasHeight = canvasHeight + snapRailHFor(data) + stripCount * BEAT_STRIP_H;

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
        {uri && (
          <ShowCueBar uri={uri} durationMs={durationMs} cues={analysedPlan?.show_cues} arms={showArms}
            beats={librosa?.beats ?? null}
            onChanged={() => void refetchAnalysedPlan()} />
        )}
      </CollapsibleCard>

      <SpectraTriggersCard
        uri={uri}
        durationMs={durationMs}
        getWin={followWin.getWin}
        getNowMs={getNowMs}
        below={uri ? (
          <>
            {showAnalysedEvents && (
              <>
                <div className="analysed-events-strip-label">
                  <span>Analysed events</span>
                  <span className="analysed-events-strip-count">
                    {!analysedPlan
                      ? 'reading…'
                      : analysedPlan.applies
                        ? `${analysedPlan.scene_changes.length} scene changes, ${analysedPlan.flares.length} flares`
                        : `none: ${analysedPlan.reason}`}
                  </span>
                  <HelpLink topic="builder-analysed-events" title="Analysed events" />
                </div>
                <AnalysedEventsStrip markers={analysedMarkers} durationMs={durationMs} />
              </>
            )}
            <div className="drop-strip-label">
              <span>Drop sequences</span>
              <span className="drop-strip-count">
                {dropResp?.status === 'ok'
                  ? `${dropSeqs.filter((q) => q.number != null).length} that fire · ${dropSeqs.filter((q) => q.fire === 'waits').length} suggested`
                  : dropLoading ? 'reading…' : (dropResp?.reason ?? '')}
              </span>
              <HelpLink topic="drop-sequence-strip" title="The drop-sequence strip" />
            </div>
            <div {...{ [DROP_FOCUS_ATTR]: '' }}>
            <DropSequenceStrip
              seqs={dropSeqs}
              durationMs={durationMs}
              capturedFromMs={dropCapturedFrom}
              selectedKey={dropSel}
              getWin={followWin.getWin}
              getNowMs={getNowMs}
              onPick={(key) => { dropUi.select(key); jumpToDrop(key); }}
            />
            </div>
          </>
        ) : null}
      />

      <CollapsibleCard
        id="shape"
        wrapHeader
        title={<>Audio Shape <HelpLink topic="builder-mouse" title="Canvas mouse actions" />
          <HelpLink topic="builder-selection-keys" title="Selection & intensity keys" /></>}
        headerExtra={
          // Wraps rather than widening the page on a phone (390 px).
          <span style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap',
                         justifyContent: 'flex-end', minWidth: 0 }}>
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
              className={`chip filter ${showAnalysedEvents ? 'active' : ''}`}
              title="Show/hide SPECTRA's planned scene changes and analysed flares for this song, on the graph and on the trigger strip"
              onClick={() => setShowAnalysedEvents((v) => !v)}
            >
              Analysed events
            </button>
            <button
              style={{ fontSize: 12 }}
              className={`chip filter ${showDropSeqs ? 'active' : ''}`}
              title="Show/hide the drop sequences (charge → lull → drop) and the snap rails under them"
              onClick={() => setShowDropSeqs((v) => !v)}
            >
              Drop sequences
            </button>
            <button
              style={{ fontSize: 12 }}
              className={`chip filter ${showLightShow ? 'active' : ''}`}
              title="Show/hide the Light Show's High/Low Trigger positions — solid when an action set is armed on it, muted when nothing is"
              onClick={() => setShowLightShow((v) => !v)}
            >
              Light Show
            </button>
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
        <div ref={canvasWrapRef} style={{ scrollMarginTop: 12 }} {...{ [DROP_FOCUS_ATTR]: '' }}>
        <TimelineCanvas
          layers={BUILDER_LAYERS}
          data={data}
          view={view}
          getWin={followWin.getWin}
          getNowMs={getCanvasNowMs}
          height={totalCanvasHeight}
          pointer={{
            ...triggerPointer,
            // A drop-sequence hit (./canvas/dropSeqLayer.ts) selects that
            // sequence for its detail box and goes no further — it is never
            // handed to the legacy trigger interactions, which would read it
            // as "empty canvas" (clearing a selection, or creating a trigger
            // on a double-click).
            onHit: (hit, ev, g) => {
              if (showDropSeqs && dropUi.onHit(hit, ev, g)) return;
              if (lightShowUi.pointer.onHit(hit, ev, g)) return;
              triggerPointer.onHit?.(hit, ev, g);
            },
            onDragMove: (ev, g) => {
              if (dropUi.onDragMove(ev, g)) return;
              if (lightShowUi.pointer.onDragMove(ev, g)) return;
              triggerPointer.onDragMove?.(ev, g);
            },
            onDragEnd: (ev, g) => {
              if (dropUi.onDragEnd(ev, g)) return;
              if (lightShowUi.pointer.onDragEnd(ev, g)) return;
              triggerPointer.onDragEnd?.(ev, g);
            },
            onIdleMove: showDropSeqs ? dropUi.onIdleMove : undefined,
            cursorFor: showDropSeqs ? dropUi.cursorFor : undefined,
            onDoubleClick: (ms, y, hit, g) => {
              if (dropUi.onDoubleHit(hit)) return;
              triggerPointer.onDoubleClick?.(ms, y, hit, g);
            },
            onHoverMove: (hit) => {
              const next = hit?.kind === 'drop-seq' ? { key: hit.key, handle: hit.handle } : null;
              setDropHover((prev) => (prev?.key === next?.key && prev?.handle === next?.handle ? prev : next));
              triggerPointer.onHoverMove?.(hit?.kind === 'drop-seq' ? null : hit);
            },
            onContextMenu: (ms, hit, y, g) =>
              triggerPointer.onContextMenu?.(ms, hit?.kind === 'drop-seq' ? null : hit, y, g),
            onPan: (deltaMs) => {
              const w = followWin.getWin();
              followWin.setFollow(false);
              followWin.setManualWin({ startMs: w.startMs + deltaMs, endMs: w.endMs + deltaMs });
            },
          }}
        />
        </div>
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
        <div
          data-testid="analysed-events-legend"
          style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12, marginTop: 6, fontSize: 11, color: 'var(--text-muted)' }}
        >
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span style={{ display: 'inline-block', width: 0, height: 0, borderLeft: '5px solid transparent', borderRight: '5px solid transparent', borderTop: `8px solid ${SCENE_MARKER_COLOR}` }} />
            <span style={{ display: 'inline-block', width: 2, height: 12, background: SCENE_MARKER_COLOR }} />
            Scene change
          </span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: FLARE_MARKER_COLOR }} />
            <span style={{ display: 'inline-block', width: 0, height: 12, borderLeft: `2px dashed ${FLARE_MARKER_COLOR}` }} />
            Analysed flare
          </span>
          <span style={{ minWidth: 0 }} title="Each marker's size and brightness follow its rank among the song's transitions (by section-energy change); hover a marker for its rank">
            bigger · brighter = stronger
          </span>
          <span style={{ minWidth: 0 }}>also drawn on the trigger strip above</span>
          <span style={{ minWidth: 0 }}>
            {!showAnalysedEvents
              ? 'analysed events hidden — click "Analysed events" above to show them'
              : !uri
                ? 'analysed events: —'
                : !analysedPlan
                  ? 'analysed events: —'
                  : analysedPlan.applies
                    ? `${analysedPlan.scene_changes.length} scene changes${analysedPlan.scene_source === 'planned' ? ' (planned — not generated yet)' : ''}, ${analysedPlan.flares.length} analysed flares planned`
                    : `no analysed events: ${analysedPlan.reason}`}
          </span>
          <HelpLink topic="builder-analysed-events" />
        </div>
        {showLightShow && uri && (
          <div
            data-testid="light-show-legend"
            style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12, marginTop: 4, fontSize: 11, color: 'var(--text-muted)' }}
          >
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <span style={{ display: 'inline-block', width: 0, height: 0, borderLeft: '5px solid transparent', borderRight: '5px solid transparent', borderBottom: `7px solid ${LIGHT_SHOW_COLOR.high}` }} />
              High Trigger
            </span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <span style={{ display: 'inline-block', width: 0, height: 0, borderLeft: '5px solid transparent', borderRight: '5px solid transparent', borderTop: `7px solid ${LIGHT_SHOW_COLOR.low}` }} />
              Low Trigger
            </span>
            <span style={{ minWidth: 0 }}>solid = an action set is armed and fires here · muted/dashed = nothing armed</span>
            {!!armedSceneChangeSets.length && (
              <span style={{ minWidth: 0 }} title={armedSceneChangeSets.map((a) => a.label || 'an action').join(', ')}>
                {armedSceneChangeSets.length} armed on the next scene change (no fixed position to mark)
              </span>
            )}
            <HelpLink topic="show-high-low-triggers" title="High and Low Triggers" />
          </div>
        )}
        {showDropSeqs && uri && (
          <div
            data-testid="drop-sequences-legend"
            style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12, marginTop: 4, fontSize: 11, color: 'var(--text-muted)' }}
          >
            <span className="drop-legend-item"><span className="drop-swatch charge" style={{ color: PHASE_COLOR.charge }} />charge build</span>
            <span className="drop-legend-item"><span className="drop-swatch lull" style={{ color: PHASE_COLOR.lull }} />lull</span>
            <span className="drop-legend-item"><span className="drop-swatch drop" style={{ color: PHASE_COLOR.drop }} />drop</span>
            <span style={{ minWidth: 0 }}>solid = fires · dashed = suggested · dotted = where the analysis had it</span>
            <span style={{ minWidth: 0 }}>rails under the graph: bass spikes (taller = harder) and beats</span>
            <HelpLink topic="drop-sequence-layer" title="The drop-sequence layer" />
          </div>
        )}
        {showDropSeqs && uri && (
          <DropSeqToolbar
            editor={dropEditor}
            selected={selectedDrop}
            adding={dropUi.adding}
            setAdding={dropUi.setAdding}
            focus={dropUi.focus}
            onShowDetail={showDropDetail}
          />
        )}
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

      {uri && (
        <div ref={detailRef} style={{ scrollMarginTop: 12 }}>
          <CollapsibleCard
            id="drop-sequences"
            wrapHeader
            title={<>Drop sequences <HelpLink topic="drop-sequences" title="Drop sequences" /></>}
          >
            <DropSequencesCard
              resp={dropResp}
              loading={dropLoading}
              error={dropError ? (dropError as Error).message : null}
              seqs={dropSeqs}
              selectedKey={dropSel}
              onSelect={(key) => dropUi.select(key)}
              onJump={jumpToDrop}
              showDismissed={showDismissedDrops}
              setShowDismissed={setShowDismissedDrops}
              analysedApplies={analysedApplies}
              analysedReason={analysedPlan?.reason ?? null}
              editor={dropEditor}
              selHandle={dropUi.selHandle}
              onSelectHandle={(h) => { dropUi.setSelHandle(h); dropUi.setFocus(true); }}
              onStep={(h, dir) => { dropUi.setFocus(true); dropUi.step(h, dir); }}
            />
          </CollapsibleCard>
        </div>
      )}

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

      <SonicChatPopover helpTopic="sonic-drops" />
    </>
  );
}
