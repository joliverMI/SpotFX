/** Home's EDITABLE copy of the global song timeline (song-layout-plan,
 * data/ui-layout-plan/report.md §5): icon toggles for which marker kinds
 * draw, a draggable/zoomable WINDOW (reusing timeline/hooks/useFollowWindow
 * — the SAME follow/manual-window mechanics the Timeline page's own
 * TimelineBar uses, via its own pointer handlers here since TimelineBar
 * itself is bound to the legacy MusicTrigger/EventOption editor model),
 * and the tuned audio shape below it sharing the identical window and
 * playhead.
 *
 * THE SHAPE IS THE TIMELINE PAGE'S OWN RENDERER (design-fidelity pass,
 * 2026-10-14 — audit H5, the glaring Home gap). It used to be a bespoke
 * 160px box drawing three thin unfilled lines with no axis, no beat
 * ticks and no control row; the approved mockup copies the Timeline
 * page's tuned canvas, so this card now mounts the REAL
 * `TimelineCanvas` + `BUILDER_LAYERS` (filled RMS terrain, time axis,
 * beat strips, analysed/drop/Light-Show markers, the one playhead) with
 * the mockup's own single thin row of controls beneath it. Read-only:
 * `triggers`/`events` are empty and no editing pointer is wired, so
 * nothing here can author anything — the Timeline page stays the editor.
 *
 * THE STRIP IS THE SHARED PAINTER (audit H3): `components/trackPainter.ts`
 * draws it, the same function the global read-only strip uses, so the
 * two can never drift apart again — plus this one's own window overlay
 * with bright edge handles.
 *
 * ONE SONG-TIME AXIS: markers draw against raw song time (the convention
 * songPositionMarkers already uses, per debug/plannedEvents.ts), and the
 * canvas's own `view.offsetMs` shifts the WAV-time shape onto it — the
 * same field BuilderPage passes. Both playheads read the ONE show clock
 * (lib/showClock.ts).
 *
 * RESPONSIVENESS (the Admiral, 2026-10-14: "the audio shape isn't as
 * responsive"). `TimelineCanvas` is itself rAF-driven and DPR-aware with
 * its own "resize only when the measured size actually changed" guard, so
 * pointing the shape at it keeps PR 424's measured fix by construction
 * rather than by this file's own hand-rolled loop. The STRIP's markers
 * still rebuild only when WHAT is drawn changes (never on a window move,
 * since a marker's x never depends on the window), and its playhead /
 * window overlay / time readout still move in one rAF loop reading refs —
 * no React render per frame. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Icon from '../components/Icon';
import IconToggle from '../components/IconToggle';
import InfoTip from '../components/InfoTip';
import {
  fmtMMSS, TRACK_HEIGHT, trackX, type UpcomingEvent,
} from '../components/songStrip';
import { paintTrack, type MarkNode } from '../components/trackPainter';
import TimelineCanvas from '../timeline/canvas/TimelineCanvas';
import { BUILDER_LAYERS } from '../timeline/canvas/layers';
import { computeAverages, computeMfccDistances } from '../timeline/canvas/data';
import {
  BEAT_STRIP_H, snapRailHFor, stripCountFor,
  type LayerDataBag, type ViewState,
} from '../timeline/canvas/frame';
import { buildDisplay } from '../timeline/dropSequences';
import { lightShowCueMarkers } from '../timeline/lightShowMarkers';
import { songPositionMarkers } from '../debug/plannedEvents';
import {
  useAnalysedPlan, useAudioShapeData, useAudioShapeMeta, useDropRails, useDropSequences,
  useLibrosa, useShowArms,
} from '../timeline/queries';
import { useFollowWindow } from '../timeline/hooks/useFollowWindow';
import { getPositionMs, getShowClockMs } from '../lib/showClock';
import { AnalysedGlyph, DropSeqGlyph, LightShowGlyph } from './markerGlyphs';

type KindFilter = { analysed: boolean; drop: boolean; lightShow: boolean };
const isAnalysed = (k: UpcomingEvent['kind']) => k === 'scene' || k === 'flare' || k === 'colour';
const isDrop = (k: UpcomingEvent['kind']) => k === 'charge' || k === 'lull' || k === 'drop';
const isLightShow = (k: UpcomingEvent['kind']) => k === 'high' || k === 'low';

/** The mockup's own canvas height (`.sp .canvasbox canvas { height: 230px }`),
 * replacing the 160px box — the Timeline page's own renderer needs real
 * room for its bands, axis and beat strips. */
const CANVAS_H = 230;

export default function HomeTimeline({
  uri, title, artist, durationMs, events, showAudioShape = true,
}: {
  uri: string | null;
  title: string;
  artist: string;
  durationMs: number;
  events: UpcomingEvent[];
  /** The kiosk view's own small-screen rule (kiosk/kioskConfig.ts): drop
   * the audio shape rather than squeeze it illegible. */
  showAudioShape?: boolean;
}) {
  const { data: meta } = useAudioShapeMeta(showAudioShape ? uri : null);
  const { data: shape } = useAudioShapeData(showAudioShape ? uri : null, true);
  const { data: librosa } = useLibrosa(uri);
  const { data: analysedPlan } = useAnalysedPlan(uri);
  const { data: showArms } = useShowArms(!!uri);
  const { data: dropResp } = useDropSequences(uri);
  const { data: dropRails } = useDropRails(uri, true);
  const offsetMs = Number(meta?.timestamp_offset_ms ?? 0);
  const sections = librosa?.sections ?? null;

  const [filters, setFilters] = useState<KindFilter>({ analysed: true, drop: true, lightShow: true });
  const toggle = (k: keyof KindFilter) => setFilters((f) => ({ ...f, [k]: !f[k] }));
  // The mockup's own thin control row under the shape: which bands draw,
  // the marks, and the librosa lanes — real filters, wired straight into
  // the canvas's own ViewState (the same fields BuilderPage sets).
  const [bands, setBands] = useState({ total: true, bass: true, mid: true, high: true, marks: true });
  const [lanes, setLanes] = useState({ sections: true, beats: true, more: false });
  const [intensityBg, setIntensityBg] = useState(false);

  const shown = useMemo(() => events.filter((e) => (
    (filters.analysed && isAnalysed(e.kind))
    || (filters.drop && isDrop(e.kind))
    || (filters.lightShow && isLightShow(e.kind))
  )), [events, filters]);

  const getNowForWin = useMemo(() => () => getShowClockMs(), []);
  const win = useFollowWindow({ getNowMs: getNowForWin, durationMs: Math.max(1, durationMs), keyPrefix: 'home' });
  // useFollowWindow returns a fresh object every render — only its own
  // `getWin` property is a stable (useCallback-memoized) function. Reading
  // it through a ref, rather than listing `win` in an effect's deps, is
  // what lets the rAF loop below never re-run on an unrelated re-render.
  const winRef = useRef(win);
  winRef.current = win;

  // UNDO/REDO OVER THE WINDOW (audit H2 — the mockup draws both buttons
  // beside Follow / Full song). They step this card's own view history:
  // each committed window change (a drag ending, Follow, Full song) pushes
  // the previous window, so the pair has real agency rather than being a
  // control that implies an edit Home cannot make (this app's own
  // "a box he cannot untick still implies agency" rule — see the
  // charge/lull Override Blend entry in AGENTS.md).
  const [past, setPast] = useState<{ startMs: number; endMs: number; follow: boolean }[]>([]);
  const [future, setFuture] = useState<{ startMs: number; endMs: number; follow: boolean }[]>([]);
  const snapshot = useCallback(() => {
    const w = winRef.current.getWin();
    return { startMs: w.startMs, endMs: w.endMs, follow: winRef.current.follow };
  }, []);
  const pushHistory = useCallback(() => {
    setPast((p) => [...p.slice(-19), snapshot()]);
    setFuture([]);
  }, [snapshot]);
  const restore = (s: { startMs: number; endMs: number; follow: boolean }) => {
    if (s.follow) win.setFollowSnapped(true);
    else { win.setFollow(false); win.setManualWin({ startMs: s.startMs, endMs: s.endMs }); }
  };
  const undo = () => {
    if (past.length === 0) return;
    const now = snapshot();
    const prev = past[past.length - 1];
    setPast((p) => p.slice(0, -1));
    setFuture((f) => [now, ...f].slice(0, 20));
    restore(prev);
  };
  const redo = () => {
    if (future.length === 0) return;
    const now = snapshot();
    const nxt = future[0];
    setFuture((f) => f.slice(1));
    setPast((p) => [...p.slice(-19), now]);
    restore(nxt);
  };

  const stripRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const markersGroupRef = useRef<SVGGElement>(null);
  const markNodesRef = useRef<MarkNode[]>([]);
  const windowOverlayRef = useRef<HTMLDivElement>(null);
  const playheadRef = useRef<SVGGElement>(null);
  const timeRef = useRef<HTMLSpanElement>(null);

  // The strip's own body: the SHARED painter, so Home and the global
  // strip draw one picture. Rebuilt only when WHAT is drawn changes, and
  // on resize (the painter rewrites the viewBox from the measured box).
  useEffect(() => {
    const svg = svgRef.current;
    const group = markersGroupRef.current;
    if (!svg || !group) return undefined;
    const build = () => {
      markNodesRef.current = paintTrack(svg, group, { events: shown, durationMs, sections });
    };
    build();
    const observer = new ResizeObserver(build);
    observer.observe(svg);
    return () => observer.disconnect();
  }, [shown, durationMs, sections]);

  // THE STRIP's own rAF loop — the window-overlay rect, its playhead, the
  // time readout and the passed-marker fade. The SHAPE has its own
  // rAF loop inside TimelineCanvas, so nothing here draws it.
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const w = winRef.current.getWin();
      const span = Math.max(1, w.endMs - w.startMs);
      if (windowOverlayRef.current) {
        windowOverlayRef.current.style.left = `${(w.startMs / Math.max(1, durationMs)) * 100}%`;
        windowOverlayRef.current.style.width = `${(span / Math.max(1, durationMs)) * 100}%`;
      }
      const now = getShowClockMs();
      const pos = getPositionMs();
      const svgW = svgRef.current?.getBoundingClientRect().width ?? 0;
      if (playheadRef.current && now != null && durationMs > 0 && svgW > 0) {
        playheadRef.current.setAttribute('transform', `translate(${trackX(now, durationMs, svgW).toFixed(2)},0)`);
        playheadRef.current.setAttribute('opacity', '1');
      } else {
        playheadRef.current?.setAttribute('opacity', '0');
      }
      if (timeRef.current) {
        timeRef.current.textContent = pos != null && durationMs > 0
          ? `${fmtMMSS(pos)} / ${fmtMMSS(durationMs)}` : '—:— / —:—';
      }
      if (now != null) {
        for (const m of markNodesRef.current) {
          m.node.classList.toggle('song-strip-mk-past', m.ms < now - 50);
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [durationMs]);

  // ── the shape: the Timeline page's own canvas, read-only ───────────────
  const averages = useMemo(() => (shape ? computeAverages(shape, 4000) : null), [shape]);
  const mfccDistances = useMemo(() => computeMfccDistances(librosa ?? null), [librosa]);
  const maxRms = useMemo(() => (shape ? Math.max(...shape.rms_total, 1e-9) : null), [shape]);
  const analysedMarkers = useMemo(
    () => (filters.analysed ? songPositionMarkers(analysedPlan) : []), [filters.analysed, analysedPlan]);
  const lightShowCues = useMemo(
    () => (filters.lightShow ? lightShowCueMarkers(analysedPlan?.show_cues, showArms, uri) : []),
    [filters.lightShow, analysedPlan, showArms, uri]);
  const dropSeqs = useMemo(
    () => (filters.drop ? buildDisplay(dropResp, { showDismissed: false, analysedApplies: analysedPlan?.applies ?? true }) : []),
    [filters.drop, dropResp, analysedPlan]);

  const view: ViewState = useMemo(() => ({
    filters: bands,
    avgFilters: { total: false, bass: false, mid: false, high: false },
    // Every MusicMark kind, gated as one by the "Marks" toggle below —
    // Home is a glance view, not the Timeline page's per-kind legend.
    markFilters: {
      bass_drop: bands.marks, bass_start: bands.marks, bass_end: bands.marks,
      power_up: bands.marks, power_down: bands.marks, quiet: bands.marks,
      charging: bands.marks, tempo_change: bands.marks,
    },
    librosaFilters: {
      sections: lanes.sections, beats: lanes.beats,
      // The mockup's own "⋯ More lanes: onsets, harmonic, bass, snare,
      // mfcc" — one toggle over the set, since Home is a glance view and
      // the Timeline page already has the per-lane legend.
      onsets: lanes.more, harmonic: lanes.more,
      bass: lanes.more, snare: lanes.more, mfcc: lanes.more,
    },
    scales: { total: 1, bass: 1, mid: 1, high: 1 },
    scaleOverall: 1,
    offsetMs,
    librosaOffsetMs: Number((librosa as { librosa_offset_ms?: number } | undefined)?.librosa_offset_ms ?? 0),
    triggerOffsetMs: 0,
    maxRms,
    intensityMode: intensityBg ? 'total' : 'off',
    advanced: false,
  }), [bands, lanes, intensityBg, offsetMs, librosa, maxRms]);

  const data: LayerDataBag = useMemo(() => ({
    shape: shape ?? null,
    averages,
    meta: meta ?? null,
    librosa: librosa ?? null,
    mfccDistances,
    triggers: [],
    events: [],
    calibrationTargetsMs: [],
    draggingIntensity: null,
    selectedIds: [],
    hoverTriggerId: null,
    plannedEvents: analysedMarkers,
    dropSeq: dropSeqs.length || dropRails?.status === 'ok'
      ? {
        seqs: dropSeqs, rails: dropRails?.status === 'ok' ? dropRails : null,
        selectedKey: null, hover: null, selectedHandle: null, adding: false, live: null,
        capturedFromMs: dropResp?.song?.captured_from_ms ?? null,
        beatMs: dropResp?.song?.beat_ms ?? dropRails?.beat_ms ?? 500,
      }
      : null,
    lightShow: lightShowCues,
  }), [shape, averages, meta, librosa, mfccDistances, analysedMarkers, dropSeqs, dropRails,
       dropResp, lightShowCues]);

  const canvasHeight = CANVAS_H
    + snapRailHFor(data)
    + stripCountFor(data, view.librosaFilters) * BEAT_STRIP_H;

  // Window drag — TimelineBar's own dragEdge shape (BuilderPage.tsx's
  // onAdjustFollow convention): in follow mode, an edge drag resizes the
  // look-ahead/window size; a center drag always detaches into a manual
  // pan (the plan's own "dragging leaves Follow" rule).
  const dragWin = (edge: 'start' | 'end' | 'center') => (ev: React.PointerEvent) => {
    ev.preventDefault(); ev.stopPropagation();
    const strip = stripRef.current;
    if (!strip) return;
    pushHistory();
    (ev.target as HTMLElement).setPointerCapture(ev.pointerId);
    let lastX = ev.clientX;
    const move = (e: PointerEvent) => {
      const rect = strip.getBoundingClientRect();
      const deltaMs = ((e.clientX - lastX) / Math.max(1, rect.width)) * Math.max(1, durationMs);
      lastX = e.clientX;
      if (win.follow && edge !== 'center') {
        if (edge === 'end') win.setFutureS((s) => Math.max(0, s + deltaMs / 1000));
        else win.setWindowS((s) => Math.max(2, s - deltaMs / 1000));
        return;
      }
      const w = win.getWin();
      if (edge === 'center') win.setManualWin({ startMs: w.startMs + deltaMs, endMs: w.endMs + deltaMs });
      else if (edge === 'start') win.setManualWin({ startMs: Math.min(w.startMs + deltaMs, w.endMs - 1000), endMs: w.endMs });
      else win.setManualWin({ startMs: w.startMs, endMs: Math.max(w.endMs + deltaMs, w.startMs + 1000) });
      if (edge === 'center' && win.follow) win.setFollow(false);
    };
    const up = (e: PointerEvent) => {
      (ev.target as HTMLElement).releasePointerCapture(e.pointerId);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  return (
    <div className="home-timeline card">
      <div className="home-timeline-head">
        {/* The mockup's own head: equaliser, title and artist INLINE, then
          * the marker toggles, undo/redo, Follow / Full song, and a bold
          * tabular progress (audit H2 — the live build had a "♪" text
          * glyph, title/artist stacked, and no undo/redo). */}
        <span className="song-strip-eq home-timeline-eq" aria-hidden><i /><i /><i /></span>
        <b className="home-timeline-title">{title || 'No song'}</b>
        <span className="home-timeline-artist">{artist}</span>
        <div className="home-timeline-tools">
          <IconToggle glyph={AnalysedGlyph} on={filters.analysed} onChange={() => toggle('analysed')}
            title="Analysed events (scene changes and flares)" />
          <IconToggle glyph={DropSeqGlyph} on={filters.drop} onChange={() => toggle('drop')}
            title="Drop sequences" />
          <IconToggle glyph={LightShowGlyph} on={filters.lightShow} onChange={() => toggle('lightShow')}
            title="Light Show High / Low triggers" />
          <span className="home-timeline-vsep" aria-hidden />
          <button type="button" className="home-timeline-tool" onClick={undo} disabled={past.length === 0}
            title="Undo the last view change" aria-label="Undo the last view change">
            <Icon name="undo" size={15} />
          </button>
          <button type="button" className="home-timeline-tool" onClick={redo} disabled={future.length === 0}
            title="Redo the view change" aria-label="Redo the view change">
            <Icon name="redo" size={15} />
          </button>
          <span className="home-timeline-vsep" aria-hidden />
          <button type="button" className={`home-timeline-tool${win.follow ? ' home-timeline-tool-on' : ''}`}
            title="Follow the playhead" aria-label="Follow the playhead"
            onClick={() => { pushHistory(); win.setFollowSnapped(!win.follow); }}>
            <Icon name="follow" size={15} />
          </button>
          <button type="button" className="home-timeline-tool" title="Whole song" aria-label="Whole song"
            onClick={() => { pushHistory(); win.fullSong(); }}>
            <Icon name="full" size={15} />
          </button>
          {/* The page's own help lives on the clock's hover description —
            * no visible circle here either (idea 5's "one help '?' per
            * page", which is the menu's own). */}
          <InfoTip topic="home-page"
            text="The whole song with everything that will fire, and the tuned audio shape below it. Drag the window on the strip to zoom; ◎ follows the playhead, ↔ shows the whole song.">
            <span ref={timeRef} className="home-timeline-clock tabular-nums">—:— / —:—</span>
          </InfoTip>
        </div>
      </div>

      <div ref={stripRef} className="home-timeline-strip">
        <svg ref={svgRef} className="song-strip-svg" preserveAspectRatio="none"
            viewBox={`0 0 100 ${TRACK_HEIGHT}`} role="img"
            aria-label={`${title || 'No song'}: whole song with planned events`}>
          <g ref={markersGroupRef} />
          <g ref={playheadRef} opacity="0">
            <line x1="0" x2="0" y1="0" y2={TRACK_HEIGHT} className="song-strip-playhead" />
            <path d="M-4 0 L4 0 L0 5Z" fill="#fff" />
          </g>
        </svg>
        <div ref={windowOverlayRef} className="home-timeline-window" onPointerDown={dragWin('center')}>
          <div className="home-timeline-window-edge left" onPointerDown={dragWin('start')} />
          <div className="home-timeline-window-edge right" onPointerDown={dragWin('end')} />
        </div>
      </div>

      {showAudioShape && (
        <>
          <div className="home-timeline-shape">
            <TimelineCanvas
              layers={BUILDER_LAYERS}
              data={data}
              view={view}
              getWin={win.getWin}
              getNowMs={getShowClockMs}
              height={canvasHeight}
            />
          </div>
          {/* ONE THIN ROW of controls, the mockup's own (audit H5 — the
            * live build had none at all). */}
          <div className="home-timeline-controls">
            <div className="home-timeline-controls-group">
              <IconToggle label="T" size={28} on={bands.total} title="Total RMS"
                onChange={() => setBands((b) => ({ ...b, total: !b.total }))} />
              <IconToggle label="B" size={28} on={bands.bass} title="Bass RMS"
                onChange={() => setBands((b) => ({ ...b, bass: !b.bass }))} />
              <IconToggle label="M" size={28} on={bands.mid} title="Mid RMS"
                onChange={() => setBands((b) => ({ ...b, mid: !b.mid }))} />
              <IconToggle label="H" size={28} on={bands.high} title="High RMS"
                onChange={() => setBands((b) => ({ ...b, high: !b.high }))} />
              <span className="home-timeline-vsep" aria-hidden />
              <IconToggle label="Marks" size={28} on={bands.marks} title="The song's own marks"
                onChange={() => setBands((b) => ({ ...b, marks: !b.marks }))} />
              <span className="home-timeline-vsep" aria-hidden />
              <IconToggle label="sections" size={28} on={lanes.sections} title="Librosa section boundaries"
                onChange={() => setLanes((l) => ({ ...l, sections: !l.sections }))} />
              <IconToggle label="beats" size={28} on={lanes.beats} title="Librosa beat strips"
                onChange={() => setLanes((l) => ({ ...l, beats: !l.beats }))} />
              <IconToggle icon="more" size={28} on={lanes.more}
                title="More lanes: onsets, harmonic, bass, snare, mfcc"
                onChange={() => setLanes((l) => ({ ...l, more: !l.more }))} />
            </div>
            <div className="home-timeline-controls-group">
              <IconToggle icon="bolt" size={28} on={intensityBg}
                title="Shade the background by the song's own intensity"
                onChange={() => setIntensityBg((v) => !v)} />
              <InfoTip topic="builder-analysed-events"
                text="Cyan squares are scene changes and lime dots analysed flares, sized and shaded by rank. Gold is a charge, sky a lull, pink a drop. White and indigo flags are the Light Show's High and Low Triggers.">
                <span className="home-timeline-tool home-timeline-tool-wide">
                  <Icon name="info" size={14} /> Legend
                </span>
              </InfoTip>
              <a className="home-timeline-tool home-timeline-tool-wide" href="/spectra/timeline"
                title="Open the Timeline page to edit this song">
                <Icon name="timeline" size={14} /> Timeline
              </a>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
